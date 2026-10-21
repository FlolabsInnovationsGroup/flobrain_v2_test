"""Social connector registry (spec 8.7 step 13).

A connector implements ``authorize_url``, ``exchange_code``, ``refresh``,
``create_post`` and ``capabilities``. It is offered only when its app
credentials are configured (``SOCIAL_<PLATFORM>_CLIENT_ID`` / ``_SECRET``);
otherwise the platform shows as "Not configured". No live connector ships in
this phase (company developer apps, Q16). ``sandbox`` is a local stand-in for
tests and demos, enabled by ``SOCIAL_SANDBOX_ENABLED`` or ``DEMO_MODE``; its posts go to
``sandbox.invalid`` and nowhere else.
"""

from django.conf import settings


class ConnectorError(Exception):
    def __init__(self, code, transient=False):
        super().__init__(code)
        self.code, self.transient = code, transient


class BaseConnector:
    platform = ""
    label = ""
    unaudited_private = False  # e.g. TikTok/YouTube before app audit: posts are private (Q16)

    def configured(self) -> bool:
        p = self.platform.upper()
        return bool(getattr(settings, f"SOCIAL_{p}_CLIENT_ID", "") and getattr(settings, f"SOCIAL_{p}_CLIENT_SECRET", ""))

    def capabilities(self) -> dict:
        return {"max_duration_seconds": 600, "aspect_ratios": ["9:16", "16:9", "1:1"], "caption_max": 2200}

    def authorize_url(self, state, code_challenge, redirect_uri) -> str:
        raise ConnectorError("not_configured")

    def exchange_code(self, code, verifier, redirect_uri) -> dict:
        """Return {"tokens": {...}, "display_name": str, "account_id": str, "scopes": [...]}."""
        raise ConnectorError("not_configured")

    def create_post(self, tokens, media_url, title, description, hashtags, private) -> dict:
        """Return {"id": str, "url": str}. Raise ConnectorError(transient=True) to retry."""
        raise ConnectorError("not_configured")


class SandboxConnector(BaseConnector):
    platform = "sandbox"

    @property
    def label(self):
        return "Sandbox (demo)" if getattr(settings, "DEMO_MODE", False) else "Sandbox (test only)"

    def configured(self) -> bool:
        return bool(getattr(settings, "SOCIAL_SANDBOX_ENABLED", False) or getattr(settings, "DEMO_MODE", False))

    def authorize_url(self, state, code_challenge, redirect_uri):
        return f"https://sandbox.invalid/authorize?state={state}&code_challenge={code_challenge}&redirect_uri={redirect_uri}"

    def exchange_code(self, code, verifier, redirect_uri):
        if code != "good-code" or not verifier:
            raise ConnectorError("invalid_code")
        name = "Sandbox (demo)" if getattr(settings, "DEMO_MODE", False) else "Sandbox account"
        return {"tokens": {"access_token": "sandbox-token"}, "display_name": name, "account_id": "sb-1", "scopes": ["post"]}

    def create_post(self, tokens, media_url, title, description, hashtags, private):
        if tokens.get("access_token") != "sandbox-token":
            raise ConnectorError("invalid_credential")
        import secrets

        post_id = f"sb-{secrets.token_hex(6)}"
        return {"id": post_id, "url": f"https://sandbox.invalid/post/{post_id}"}


class _Named(BaseConnector):
    def __init__(self, platform, label, unaudited_private=False):
        self.platform, self.label, self.unaudited_private = platform, label, unaudited_private


REGISTRY = {
    "youtube": _Named("youtube", "YouTube", unaudited_private=True),
    "linkedin": _Named("linkedin", "LinkedIn"),
    "tiktok": _Named("tiktok", "TikTok", unaudited_private=True),
    "instagram": _Named("instagram", "Instagram"),
    "facebook": _Named("facebook", "Facebook"),
    "x": _Named("x", "X"),
    "sandbox": SandboxConnector(),
}


def get(platform):
    return REGISTRY.get(platform)


def platforms():
    return [
        {
            "platform": c.platform,
            "label": c.label,
            "configured": c.configured(),
            "posts_private_until_audit": c.unaudited_private,
            "capabilities": c.capabilities(),
        }
        for c in REGISTRY.values()
        if c.platform != "sandbox" or c.configured()
    ]
