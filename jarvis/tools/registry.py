from typing import Callable

from jarvis.exceptions import InvalidArgumentError, ToolNotFoundError
from jarvis.tools.get_doc import get_doc
from jarvis.tools.get_list import get_list
from jarvis.tools.get_schema import get_schema
from jarvis.tools.run_report import run_report

_TOOLS: dict[str, Callable] = {
    "get_schema": get_schema,
    "get_doc": get_doc,
    "get_list": get_list,
    "run_report": run_report,
}


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
