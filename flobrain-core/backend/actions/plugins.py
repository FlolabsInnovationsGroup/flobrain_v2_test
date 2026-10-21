"""Tools that other apps add to the action registry (2026-10-21).

An app registers a tool once, from its ``AppConfig.ready()``::

    from actions.plugins import register_tool

    register_tool("jira.create_issue", spec, check=_check, execute=_execute)

``spec`` has the same shape as an entry in ``actions.registry.TOOLS`` (``perm_key``, ``risk``,
``label``, ``description``, ``schema``). ``check(user, org, args) -> str`` raises
``actions.service.ActionDenied`` or returns the one-line summary shown on the approval card.
``execute(user, org, args) -> dict`` runs the approved call. Both run after the shared checks
(tool enabled, permission held), so a plugin only checks its own target. Writes are never run
without an approved ``ActionProposal``; that rule lives in ``actions.service`` and does not change.
"""

from dataclasses import dataclass
from typing import Callable

from actions.registry import TOOLS


@dataclass(frozen=True)
class ToolHandler:
    check: Callable
    execute: Callable


_HANDLERS: dict[str, ToolHandler] = {}


def register_tool(key: str, spec: dict, *, check: Callable, execute: Callable) -> None:
    if key in TOOLS and key not in _HANDLERS:
        raise ValueError(f"{key} is a built-in tool")
    for field in ("perm_key", "risk", "label", "description", "schema"):
        if field not in spec:
            raise ValueError(f"{key}: missing {field}")
    TOOLS[key] = spec
    _HANDLERS[key] = ToolHandler(check=check, execute=execute)


def handler(key: str) -> ToolHandler | None:
    return _HANDLERS.get(key)
