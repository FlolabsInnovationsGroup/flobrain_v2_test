"""Area-specific demo data. Each module here defines ``seed(org, users, now)``; ``demo.seed.reset``
runs them all, in module-name order, after the core demo is built. ``users`` maps role keys
(owner, admin, lead, member, designer) to User rows. Rooms, teams and the project can be looked
up by name in ``org``. Keep everything clearly demo (labelled text, example.com addresses)."""

import importlib
import pkgutil


def run_all(org, users, now):
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        seed = getattr(module, "seed", None)
        if callable(seed):
            seed(org, users, now)
