"""Built-in demo endpoints that never touch the network (DEMO_MODE only).

The demo MCP server and the demo webhook inbox live in this process. Their URLs use the
reserved ``.invalid`` top-level domain, so outside demo mode they fail the normal SSRF check
(they do not resolve) exactly like any other unknown host: nothing is special-cased there.
"""

import urllib.parse

from django.conf import settings

DEMO_MCP_HOST = "mcp.demo.flobrain.invalid"
DEMO_INBOX_HOST = "inbox.demo.flobrain.invalid"
DEMO_MCP_URL = f"https://{DEMO_MCP_HOST}/mcp"
DEMO_HOSTS = (DEMO_MCP_HOST, DEMO_INBOX_HOST)


def enabled() -> bool:
    return bool(getattr(settings, "DEMO_MODE", False))


def host_of(url) -> str:
    try:
        return (urllib.parse.urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def is_demo_url(url, host=None) -> bool:
    """True only in demo mode, only for an https URL on one of the built-in demo hosts."""
    if not enabled():
        return False
    try:
        parsed = urllib.parse.urlparse(url or "")
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
        return False
    wanted = (host,) if host else DEMO_HOSTS
    return (parsed.hostname or "").lower() in wanted


def inbox_url(org) -> str:
    return f"https://{DEMO_INBOX_HOST}/{org.id}"
