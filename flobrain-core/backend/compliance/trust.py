"""Trust center: a public page an org chooses to publish at ``/trust/<slug>``. Off until published.

The public projection shows only the sections the org turned on, and for controls only readiness numbers by
framework and group (no control evidence, no failing check names, no people). It always says "readiness",
never "certified".
"""

from __future__ import annotations

import hashlib
import re

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.text import slugify

from compliance.models import TrustCenter, TrustRequest

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,78}[a-z0-9])?$")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_SUBPROCESSORS = 50
MAX_DOCUMENTS = 20
IP_LIMIT_PER_HOUR = 3
ORG_LIMIT_PER_DAY = 30
CACHE_SECONDS = 600
DISCLAIMER = "Readiness, not certification: these numbers come from automated checks and our own attestations, not from an auditor."

# FloBrain's own trust page content, shipped as an example (the demo publishes it). Confirm every line
# against real contracts before a production trust page uses it.
FLOBRAIN_EXAMPLE = {
    "headline": "Security at FloBrain",
    "overview": (
        "FloBrain is an AI workspace where people approve what AI does. Data is encrypted in transit with TLS "
        "and secrets are encrypted at rest with AES-256-GCM. Single sign-on (OIDC and SAML) and SCIM are available. "
        "Every AI action that writes outside the workspace or sends a message waits for a person's approval. "
        "Admin and access changes are kept in an audit log. Owners can require self-hosted AI models only. "
        "We are working toward SOC 2 Type II and ISO/IEC 27001:2022; we are not certified yet."
    ),
    "subprocessors": [
        {"name": "Amazon Web Services", "purpose": "Hosting, database and file storage", "location": "United States (us-east-1)", "website": "https://aws.amazon.com"},
        {"name": "AI model providers you turn on", "purpose": "Language models, only when your owner allows external AI", "location": "Depends on the provider", "website": ""},
        {"name": "Stripe", "purpose": "Payments and billing", "location": "United States", "website": "https://stripe.com"},
        {"name": "Vercel", "purpose": "Website hosting", "location": "United States", "website": "https://vercel.com"},
        {"name": "Sentry", "purpose": "Error monitoring (no message content)", "location": "United States", "website": "https://sentry.io"},
    ],
    "data_location": "United States (AWS us-east-1). Meetings are transcribed on FloBrain's own Whisper server; no outside speech service.",
    "documents": [
        {"key": "soc2-readiness", "title": "SOC 2 readiness summary", "description": "Our control status by criteria, refreshed monthly."},
        {"key": "policies", "title": "Security policies", "description": "Information security, access control, incident response and more."},
        {"key": "pentest", "title": "Penetration test summary", "description": "Available after the first external test."},
        {"key": "dpa", "title": "Data processing agreement", "description": "Our standard DPA for customers."},
    ],
    "sections": ["overview", "controls", "subprocessors", "data_location", "documents"],
}


def default_slug(org) -> str:
    base = slugify(org.slug or org.name)[:70] or "trust"
    slug, n = base, 2
    while TrustCenter.objects.filter(slug=slug).exclude(org=org).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def get_or_new(org):
    trust = TrustCenter.objects.filter(org=org).first()
    if trust is None:
        trust = TrustCenter(org=org, slug=default_slug(org), sections=["overview", "controls", "subprocessors"])
    return trust


def clean_text(value, limit):
    return CONTROL.sub("", str(value or "")).strip()[:limit]


def _clean_url(value):
    url = clean_text(value, 300)
    return url if url.startswith("https://") else ""


def clean_subprocessors(rows):
    if not isinstance(rows, list):
        raise ValueError("subprocessors must be a list")
    out = []
    for row in rows[:MAX_SUBPROCESSORS]:
        if not isinstance(row, dict):
            continue
        name = clean_text(row.get("name"), 120)
        if not name:
            continue
        out.append({"name": name, "purpose": clean_text(row.get("purpose"), 200), "location": clean_text(row.get("location"), 120), "website": _clean_url(row.get("website"))})
    return out


def clean_documents(rows):
    if not isinstance(rows, list):
        raise ValueError("documents must be a list")
    out, seen = [], set()
    for row in rows[:MAX_DOCUMENTS]:
        if not isinstance(row, dict):
            continue
        title = clean_text(row.get("title"), 120)
        if not title:
            continue
        key = slugify(row.get("key") or title)[:40] or f"doc-{len(out) + 1}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "title": title, "description": clean_text(row.get("description"), 300)})
    return out


def payload(trust):
    return {
        "slug": trust.slug, "published": trust.published,
        "published_at": trust.published_at.isoformat() if trust.published_at else None,
        "sections": [s for s in trust.sections or [] if s in TrustCenter.SECTIONS],
        "all_sections": list(TrustCenter.SECTIONS),
        "headline": trust.headline, "overview": trust.overview,
        "subprocessors": trust.subprocessors or [], "data_location": trust.data_location,
        "documents": trust.documents or [], "contact_email": trust.contact_email,
        "updated_at": trust.updated_at.isoformat() if trust.updated_at else None,
        "path": f"/trust/{trust.slug}",
    }


def controls_summary(org):
    """Readiness numbers only, cached for 10 minutes so the public page does not run checks on every hit."""
    key = f"compliance:trust:controls:{org.id}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    from compliance import readiness

    summary = readiness.summarize(readiness.evaluate(org))
    out = [{
        "framework": fw["framework"], "name": fw["name"], "readiness": fw["readiness"],
        "passing": fw["counts"]["pass"], "applicable": fw["counts"]["total"] - fw["counts"]["not_applicable"],
        "groups": [{"name": g["name"], "readiness": g["readiness"]} for g in fw["groups"]],
    } for fw in summary]
    cache.set(key, out, CACHE_SECONDS)
    return out


def flush_cache(org):
    cache.delete(f"compliance:trust:controls:{org.id}")


def public_projection(trust):
    """What a signed-out visitor sees. Only published sections; nothing internal."""
    org = trust.org
    shown = [s for s in trust.sections or [] if s in TrustCenter.SECTIONS]
    out = {"org": {"name": org.name}, "slug": trust.slug, "headline": trust.headline or f"Security at {org.name}",
           "sections": shown, "disclaimer": DISCLAIMER, "updated_at": trust.updated_at.isoformat() if trust.updated_at else None}
    if "overview" in shown:
        out["overview"] = trust.overview
    if "controls" in shown:
        out["controls"] = controls_summary(org)
    if "subprocessors" in shown:
        out["subprocessors"] = [{k: row.get(k, "") for k in ("name", "purpose", "location", "website")} for row in trust.subprocessors or []]
    if "data_location" in shown:
        out["data_location"] = trust.data_location
    if "documents" in shown:
        out["documents"] = [{"key": d["key"], "title": d["title"], "description": d.get("description", "")} for d in trust.documents or []]
    return out


def published_for_slug(slug):
    from organizations.flags import effective_flag

    if not slug or not SLUG_RE.match(slug):
        return None
    trust = TrustCenter.objects.select_related("org").filter(slug=slug, published=True).first()
    if trust is None or not trust.org.is_active or not effective_flag(trust.org, None, "compliance", default=False):
        return None
    return trust


def ip_hash(ip: str) -> str:
    return hashlib.sha256(f"trust-request:{settings.SECRET_KEY[:16]}:{ip or ''}".encode()).hexdigest()


def _hit(scope, ident, limit, window):
    from channels import ratelimit

    return ratelimit.hit(f"trust-{scope}", ident, limit, window)


def allow_request(trust, ip) -> bool:
    """3 requests an hour per visitor address and 30 a day per org."""
    ok_ip = _hit("ip", f"{trust.org_id}:{ip_hash(ip)}", IP_LIMIT_PER_HOUR, 3600)
    ok_org = _hit("org", str(trust.org_id), ORG_LIMIT_PER_DAY, 86400)
    return ok_ip and ok_org


def create_request(trust, data, ip):
    known = {d["key"] for d in trust.documents or []}
    docs = [d for d in (data.get("documents") or []) if isinstance(d, str) and d in known][:MAX_DOCUMENTS]
    req = TrustRequest.objects.create(
        org=trust.org, name=clean_text(data.get("name"), 120), email=str(data.get("email")).strip().lower()[:254],
        company=clean_text(data.get("company"), 160), documents=docs, message=clean_text(data.get("message"), 1000), ip_hash=ip_hash(ip),
    )
    _tell_admins(trust, req)
    return req


def _tell_admins(trust, req):
    from compliance.reviews import reviewers_for_unassigned
    from notifications.services import notify

    org = trust.org
    admins = reviewers_for_unassigned(org)
    text = f"{req.name} from {req.company or req.email} asked for security documents"
    notify(org, admins, "compliance.trust_request", {"text": text, "title": "Trust page request", "request": str(req.id)}, link="settings/compliance?tab=trust")
    recipients = sorted({u.email for u in admins if u.email} | ({trust.contact_email} if trust.contact_email else set()))
    if recipients:
        titles = [d["title"] for d in trust.documents or [] if d["key"] in req.documents]
        send_mail(
            subject=f"Trust page request from {req.company or req.name}"[:150],
            message=(f"{req.name} <{req.email}> asked for: {', '.join(titles) or 'documents'}.\n\n"
                     f"Company: {req.company or '-'}\nMessage: {req.message or '-'}\n\n"
                     "Answer from Settings > Compliance > Trust center. Check who they are before you send anything."),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=True,
        )


def request_payload(req):
    return {
        "id": str(req.id), "name": req.name, "email": req.email, "company": req.company, "documents": req.documents,
        "message": req.message, "status": req.status, "created_at": req.created_at.isoformat(),
        "handled_at": req.handled_at.isoformat() if req.handled_at else None,
        "handled_by": (req.handled_by.username or req.handled_by.email) if req.handled_by_id and req.handled_by else "",
    }


def mark(req, actor, status):
    req.status, req.handled_by, req.handled_at = status, actor, timezone.now()
    req.save(update_fields=["status", "handled_by", "handled_at"])
    return req
