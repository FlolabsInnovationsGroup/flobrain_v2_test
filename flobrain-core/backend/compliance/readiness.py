"""Control status and readiness, from the automated checks and people's attestations.

Rules for one control:
- an attestation of "not applicable" makes it not applicable (it leaves the readiness count);
- any mapped automated check that fails makes it fail; an attestation can't hide that;
- an attestation "fail" makes it fail (a known gap);
- with mapped checks: all pass (or not applicable) gives pass; a "manual" check needs an attestation "pass";
- with no mapped checks: an attestation "pass" gives pass, otherwise it is manual (needs evidence).

Readiness is passing controls / applicable controls. It is not certification.
"""

from compliance import catalog, checks
from compliance.models import ComplianceProfile, ControlAttestation

PASS, FAIL, MANUAL, NA = checks.PASS, checks.FAIL, checks.MANUAL, checks.NA


def frameworks_for(org):
    profile = ComplianceProfile.objects.filter(org=org).first()
    chosen = [f for f in (profile.frameworks if profile else []) or [] if f in catalog.FRAMEWORKS]
    return chosen or list(catalog.FRAMEWORKS)


def control_status(control, results, attestation):
    mapped = [results[k] for k in control["checks"] if k in results]
    if attestation is not None and attestation.status == ControlAttestation.NOT_APPLICABLE:
        return NA, "attested"
    if any(r["status"] == FAIL for r in mapped):
        return FAIL, "automated"
    if attestation is not None and attestation.status == ControlAttestation.FAIL:
        return FAIL, "attested"
    if mapped:
        if all(r["status"] in (PASS, NA) for r in mapped):
            if all(r["status"] == NA for r in mapped) and attestation is None:
                return MANUAL, "automated"
            return PASS, "automated"
        if attestation is not None and attestation.status == ControlAttestation.PASS:
            return PASS, "attested"
        return MANUAL, "automated"
    if attestation is not None and attestation.status == ControlAttestation.PASS:
        return PASS, "attested"
    return MANUAL, "none"


def evaluate(org, results=None, framework=None):
    """Every control with its status. ``results`` is ``checks.run_all(org)`` (computed if missing)."""
    results = results if results is not None else checks.run_all(org)
    chosen = [framework] if framework else frameworks_for(org)
    atts = {(a.framework, a.control_id): a for a in ControlAttestation.objects.filter(org=org).select_related("attested_by", "owner")}
    rows = []
    for c in catalog.CONTROLS:
        if c["framework"] not in chosen:
            continue
        att = atts.get((c["framework"], c["id"]))
        status, source = control_status(c, results, att)
        rows.append({
            **c,
            "status": status,
            "source": source,
            "check_results": [{"key": k, "status": results[k]["status"], "title": results[k]["title"]} for k in c["checks"] if k in results],
            "attestation": _attestation(att),
        })
    return rows


def _attestation(att):
    if att is None:
        return None
    return {
        "status": att.status,
        "note": att.note,
        "evidence_url": att.evidence_url,
        "owner": {"id": str(att.owner_id), "name": att.owner.username or att.owner.email} if att.owner_id and att.owner else None,
        "by": (att.attested_by.username or att.attested_by.email) if att.attested_by_id and att.attested_by else "",
        "at": att.attested_at.isoformat(),
    }


def summarize(rows):
    """Readiness by framework and by group: counts and the percentage of applicable controls passing."""
    out = {}
    for row in rows:
        fw = out.setdefault(row["framework"], {
            "framework": row["framework"], "name": catalog.FRAMEWORKS[row["framework"]]["name"],
            "short": catalog.FRAMEWORKS[row["framework"]]["short"], "counts": _zero(), "groups": {},
        })
        group = fw["groups"].setdefault(row["group"], {"group": row["group"], "name": row["group_name"], "counts": _zero()})
        for bucket in (fw["counts"], group["counts"]):
            bucket[row["status"]] += 1
            bucket["total"] += 1
    for fw in out.values():
        fw["readiness"] = _pct(fw["counts"])
        groups = list(fw["groups"].values())
        for g in groups:
            g["readiness"] = _pct(g["counts"])
        fw["groups"] = groups
    return list(out.values())


def _zero():
    return {PASS: 0, FAIL: 0, MANUAL: 0, NA: 0, "total": 0}


def _pct(counts):
    applicable = counts["total"] - counts[NA]
    return round(100 * counts[PASS] / applicable) if applicable else 0
