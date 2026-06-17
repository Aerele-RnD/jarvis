"""Tool registry + dispatch.

Tool modules live as siblings in jarvis.tools.<name>; the function
in each module is named the same as the file. Adding a new tool is
a two-step change: drop the module in, list the name in
``_TOOL_NAMES``. No additional import line needed here.

Previous shape: 11 explicit ``from jarvis.tools.<name> import <name>``
lines + an 11-entry dict literal. The repetition was a 2026-06-16
punch-list item. Now: one tuple of names, one comprehension that
walks ``importlib.import_module``. Each module is imported once at
registry-load time (Python caches it), so dispatch keeps the same
O(1) lookup behaviour.
"""
from __future__ import annotations

import importlib
from typing import Callable

from jarvis.exceptions import InvalidArgumentError, ToolNotFoundError

_TOOL_NAMES: tuple[str, ...] = (
    "get_schema",
    "get_doc",
    "get_list",
    "run_report",
    "run_query",
    "update_doc",
    "create_doc",
    "submit_doc",
    "cancel_doc",
    "delete_doc",
    "amend_doc",
)


def _resolve(name: str) -> Callable:
    mod = importlib.import_module(f"jarvis.tools.{name}")
    return getattr(mod, name)


_TOOLS: dict[str, Callable] = {name: _resolve(name) for name in _TOOL_NAMES}


def list_tools() -> list[str]:
    return sorted(_TOOLS.keys())


def dispatch(tool_name: str, args: dict):
    if tool_name not in _TOOLS:
        raise ToolNotFoundError(f"no such tool: {tool_name}")
    if not isinstance(args, dict):
        raise InvalidArgumentError("args must be a dict")
    try:
        return _TOOLS[tool_name](**args)
    except TypeError as e:
        raise InvalidArgumentError(str(e))
