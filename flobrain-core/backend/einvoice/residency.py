"""Data residency: where each kind of an org's data lives, and the AI host check for pinned orgs.

An org chooses ``data_region`` (``sa``, ``ae``, ``eg``, ``eu``, ``us``) and may pin it. The
region is stored in ``org.settings["data_region"] = {"region": "sa", "pinned": true}``.

Where data lives comes from the operator's settings (environment), never guessed:
- ``DATA_REGION_DEPLOYMENT``: region of this FloBrain deployment (app servers and, unless
  ``DATA_REGION_DATABASE`` says otherwise, the database and backups);
- files: ``CONTENT_S3_REGION`` (cloud region code, mapped below) or ``DATA_REGION_FILES``;
- AI, embeddings, transcription: the host of ``AI_DIRECT_BASE_URL``, ``EMBEDDINGS_BASE_URL``,
  ``ASR_BASE_URL`` (and the legacy ``MULTIMODAL_SERVICE_URL``). A host's region is known when it
  is listed in ``DATA_REGION_HOSTS`` (``host=sa,host2=eu``), or when it is in
  ``AI_SELF_HOSTED_HOSTS`` (then it runs in the deployment region);
- ``DATA_REGION_AI_HOSTS_<REGION>`` (comma separated) lists extra AI hosts allowed for orgs pinned
  to that region.

``allowed_ai_host(org, host)`` is the check AI calls must pass when the org pinned its region.
It lives here; enforcing it needs one hook in ``brain/llm/policy.check_ai`` (a shared file),
described in docs/v2/features/EINVOICE.md and ``check_ai_residency`` below.
"""

import urllib.parse

from django.conf import settings

from einvoice.transport import env

REGIONS = {"sa": "Saudi Arabia", "ae": "United Arab Emirates", "eg": "Egypt", "eu": "European Union", "us": "United States"}
# Cloud region codes we can place. Anything else is "unknown" until the operator names it.
CLOUD_REGIONS = {
    "me-central-1": "ae",  # AWS UAE
    "me-south-1": "bh",  # AWS Bahrain (not one of the selectable regions)
    "me-central2": "sa",  # Google Cloud Dammam
    "me-jeddah-1": "sa",  # Oracle Jeddah
    "me-riyadh-1": "sa",  # Oracle Riyadh
    "me-dubai-1": "ae",  # Oracle Dubai
    "me-abudhabi-1": "ae",  # Oracle Abu Dhabi
    "uaenorth": "ae",  # Azure
    "uaecentral": "ae",  # Azure
}
DATA_CLASSES = ("database", "files", "ai", "legacy_ai", "embeddings", "transcription")


def _host(url: str) -> str:
    return (urllib.parse.urlparse(url or "").hostname or "").lower().rstrip(".")


def _hosts(raw: str) -> set[str]:
    return {h.strip().lower().rstrip(".") for h in (raw or "").split(",") if h.strip()}


def cloud_region(code: str) -> str:
    code = (code or "").strip().lower()
    if not code:
        return ""
    if code in CLOUD_REGIONS:
        return CLOUD_REGIONS[code]
    if code.startswith(("eu-", "europe-")) or code in ("westeurope", "northeurope", "germanywestcentral", "francecentral"):
        return "eu"
    if code.startswith(("us-", "eastus", "westus", "centralus")):
        return "us"
    return "unknown"


def deployment_region() -> str:
    return env("DATA_REGION_DEPLOYMENT").lower()


def host_regions() -> dict[str, str]:
    out = {}
    for pair in env("DATA_REGION_HOSTS").split(","):
        host, _, region = pair.partition("=")
        if host.strip() and region.strip():
            out[host.strip().lower().rstrip(".")] = region.strip().lower()
    return out


def self_hosted() -> set[str]:
    return _hosts(getattr(settings, "AI_SELF_HOSTED_HOSTS", "") or "")


def region_of_host(host: str) -> str:
    host = (host or "").lower().rstrip(".")
    if not host:
        return ""
    mapped = host_regions().get(host)
    if mapped:
        return mapped
    if host in self_hosted() and deployment_region():
        return deployment_region()
    return "unknown"


def org_region(org) -> tuple[str, bool]:
    value = (org.settings or {}).get("data_region") if org is not None else None
    if not isinstance(value, dict):
        return "", False
    region = str(value.get("region") or "")
    return (region if region in REGIONS else ""), bool(value.get("pinned")) and region in REGIONS


def allowed_hosts(region: str) -> set[str]:
    return _hosts(env(f"DATA_REGION_AI_HOSTS_{region.upper()}"))


def allowed_ai_host(org, host: str) -> bool:
    """True when an AI call to ``host`` may carry this org's content. Orgs that did not pin a
    region are not restricted here (their AI policy still applies). An empty host means no
    network (the demo model or a test fake)."""
    region, pinned = org_region(org)
    if not pinned:
        return True
    host = (host or "").lower().rstrip(".")
    if not host:
        return True
    if host in allowed_hosts(region):
        return True
    return region_of_host(host) == region


def check_ai_residency(org, kind: str, target=None) -> str:
    """The hook for ``brain.llm.policy.check_ai``: "" or ``"data_region"``. Kinds as in check_ai."""
    if kind == "direct":
        host = _host(getattr(settings, "AI_DIRECT_BASE_URL", ""))
    elif kind == "embeddings":
        if getattr(settings, "EMBEDDINGS_BACKEND", "") == "fake":
            return ""
        host = _host(getattr(settings, "EMBEDDINGS_BASE_URL", ""))
    elif kind == "byok":
        host = _host(getattr(target, "base_url", "") or "")
    elif kind == "legacy":
        host = _host(getattr(settings, "MULTIMODAL_SERVICE_URL", ""))
    elif kind == "external_agent":
        host = _host(target if isinstance(target, str) else getattr(target, "url", ""))
    elif kind == "transcription":
        host = _host(getattr(settings, "ASR_BASE_URL", ""))
    else:
        host = ""
    if kind in ("byok", "external_agent", "legacy") and not host:
        region, pinned = org_region(org)
        return "data_region" if pinned else ""
    return "" if allowed_ai_host(org, host) else "data_region"


def refusal_message(org) -> str:
    region, _ = org_region(org)
    return f"Your organization keeps its data in {REGIONS.get(region, region)}. This AI service runs elsewhere, so the request was not sent."


def _entry(data_class, where, region, wanted, configured=True, note=""):
    if not configured:
        status = "not_configured"
    elif region in ("", "unknown"):
        status = "unknown"
    elif wanted and region != wanted:
        status = "mismatch"
    else:
        status = "ok"
    return {"class": data_class, "where": where, "region": region or "unknown", "status": status, "note": note}


def report(org) -> dict:
    wanted, pinned = org_region(org)
    deploy = deployment_region()
    db_region = env("DATA_REGION_DATABASE").lower() or deploy
    s3 = getattr(settings, "CONTENT_S3_REGION", "") or ""
    storage = getattr(settings, "CONTENT_STORAGE", "") or ""
    files_region = env("DATA_REGION_FILES").lower() or (cloud_region(s3) if storage == "s3" else deploy if storage == "local" else "")
    rows = [
        _entry("database", getattr(settings, "DATABASES", {}).get("default", {}).get("ENGINE", "").rsplit(".", 1)[-1], db_region, wanted, note="Messages, tasks, invoices, settings and backups"),
        _entry("files", f"s3:{s3}" if storage == "s3" else storage or "", files_region, wanted, configured=bool(storage), note="Uploads, recordings and renders"),
    ]
    for data_class, setting, note in (
        ("ai", "AI_DIRECT_BASE_URL", "Platform AI model"),
        ("legacy_ai", "MULTIMODAL_SERVICE_URL", "Legacy AI service"),
        ("embeddings", "EMBEDDINGS_BASE_URL", "Search index (embeddings)"),
        ("transcription", "ASR_BASE_URL", "Whisper transcription"),
    ):
        host = _host(getattr(settings, setting, "") or "")
        if data_class == "embeddings" and getattr(settings, "EMBEDDINGS_BACKEND", "") == "fake":
            rows.append(_entry(data_class, "local test embedder", deploy or "", wanted, configured=True, note=note))
            continue
        entry = _entry(data_class, host, region_of_host(host), wanted, configured=bool(host), note=note)
        if pinned and host and not allowed_ai_host(org, host):
            entry["status"] = "blocked"
        rows.append(entry)
    mismatches = [r["class"] for r in rows if r["status"] in ("mismatch", "blocked")]
    return {
        "region": wanted,
        "pinned": pinned,
        "regions": [{"code": code, "name": name} for code, name in REGIONS.items()],
        "deployment_region": deploy or "unknown",
        "classes": rows,
        "mismatches": mismatches,
        "allowed_ai_hosts": sorted(allowed_hosts(wanted)) if wanted else [],
    }
