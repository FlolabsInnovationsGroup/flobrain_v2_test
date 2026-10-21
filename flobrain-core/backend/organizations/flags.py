from django.conf import settings


def effective_flag(org, membership, key: str, default=False) -> bool:
    """Effective flag = org flag AND membership flag (E, entitlements in Phase 17)."""
    org_flags = (org.settings or {}).get("flags", {}) if org is not None else {}
    member_flags = (membership.feature_flags or {}) if membership is not None else {}
    if key in member_flags:
        org_value = bool(org_flags.get(key, True))
        return org_value and bool(member_flags[key])
    return bool(org_flags.get(key, default))


def client_ip(request):
    """Honor DRF_NUM_PROXIES when reading X-Forwarded-For (E19)."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    num = getattr(settings, "NUM_PROXIES", None)
    if forwarded and num:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        try:
            index = max(len(parts) - int(num) - 1, 0)
            return parts[index]
        except (TypeError, ValueError):
            return parts[0]
    if forwarded:
        return request.META.get("REMOTE_ADDR")
    return request.META.get("REMOTE_ADDR")
