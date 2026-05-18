from typing import Callable

from jarvis.exceptions import InvalidArgumentError, ToolNotFoundError
from jarvis.tools.amend_doc import amend_doc
from jarvis.tools.cancel_doc import cancel_doc
from jarvis.tools.create_doc import create_doc
from jarvis.tools.delete_doc import delete_doc
from jarvis.tools.get_doc import get_doc
from jarvis.tools.get_list import get_list
from jarvis.tools.get_schema import get_schema
from jarvis.tools.run_query import run_query
from jarvis.tools.run_report import run_report
from jarvis.tools.submit_doc import submit_doc
from jarvis.tools.update_doc import update_doc

_TOOLS: dict[str, Callable] = {
    "get_schema": get_schema,
    "get_doc": get_doc,
    "get_list": get_list,
    "run_report": run_report,
    "run_query": run_query,
    "update_doc": update_doc,
    "create_doc": create_doc,
    "submit_doc": submit_doc,
    "cancel_doc": cancel_doc,
    "delete_doc": delete_doc,
    "amend_doc": amend_doc,
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
