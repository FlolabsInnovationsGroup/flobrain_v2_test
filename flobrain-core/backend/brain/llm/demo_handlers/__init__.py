"""Extra answers for the demo model, one module per area. Each module defines
``handle(system: str, user: str, messages: list, tools: list | None)`` returning a
``ProviderResult`` (use ``brain.llm.demo_ai._result``) or ``None`` to pass. Handlers are tried in
module-name order before the built-in answers. Demo output must say it is demo output."""

import importlib
import pkgutil


def dispatch(system, user, messages, tools):
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        handle = getattr(module, "handle", None)
        if callable(handle):
            result = handle(system, user, messages, tools)
            if result is not None:
                return result
    return None
