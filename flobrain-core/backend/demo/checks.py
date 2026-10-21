from django.conf import settings
from django.core.checks import Warning, register


@register()
def demo_mode_check(app_configs, **kwargs):
    if getattr(settings, "DEMO_MODE", False) and not getattr(settings, "DEBUG", False):
        return [
            Warning(
                "DEMO_MODE is on without DEBUG. Anyone can sign in as the demo users. Use it only on a separate demo deployment.",
                id="flobrain.W010",
            )
        ]
    return []
