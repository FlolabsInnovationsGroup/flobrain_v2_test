"""CORS for the website chat API: answered only for the origins each site allows.

``django-cors-headers`` asks ``check_request_enabled`` when an origin is not in the global list.
This answers yes only for ``/api/v2/public/chat/<site_key>...`` and only when the request's
Origin is in that site's allowed origins. Every other path is left to the global setting.
"""

import re

PATH = re.compile(r"^/api/v2/public/chat/([A-Za-z0-9_-]{1,40})(?:/messages)?/?$")


def allow_site_origins(sender, request, **kwargs) -> bool:
    match = PATH.match(request.path_info or "")
    origin = request.headers.get("Origin") if hasattr(request, "headers") else None
    if not match or not origin:
        return False
    from channels.models import ChannelConnection
    from channels.views_public import allowed_origins, normalize_origin

    conn = (
        ChannelConnection.objects.filter(kind=ChannelConnection.WEBSITE, site_key=match.group(1), status=ChannelConnection.ACTIVE)
        .only("id", "config")
        .first()
    )
    return bool(conn and normalize_origin(origin) in allowed_origins(conn))
