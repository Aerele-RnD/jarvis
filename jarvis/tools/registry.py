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
import inspect
from typing import Callable

from jarvis.exceptions import InvalidArgumentError, ToolNotFoundError

_TOOL_NAMES: tuple[str, ...] = (
    "get_schema",
    "get_doc",
    "get_list",
    "run_report",
    "query",
    "update_doc",
    "create_doc",
    "submit_doc",
    "cancel_doc",
    "delete_doc",
    "amend_doc",
    # Tier 1 artifact producers: hand the agent a file/URL the customer
    # can act on, instead of a wall of JSON.
    "download_pdf",
    "attach_to_doc",
    "download_vcard",
    # Tier 2a ERPNext computed reads: numbers the LLM keeps hallucinating
    # because they need business-logic-aware math (FIFO/Moving-Avg,
    # fiscal-year boundaries, party-level GL aggregation).
    "get_stock_balance",
    "get_valuation_rate",
    "scan_barcode",
    "get_balance_on",
    "get_customer_outstanding",
    "get_party_dashboard_info",
    "get_exchange_rate",
    "get_fiscal_year",
    "get_itemised_tax_breakup",
    # Tier 2b HRMS + Frappe computed reads: leave/shift/holiday lookups
    # the LLM gets wrong because they need policy-aware math, plus
    # Frappe linked-doc walking + naming-series preview.
    "get_leave_balance_on",
    "get_leaves_for_period",
    "get_leave_details",
    "get_holidays_for_employee",
    "get_employee_shift",
    "get_linked_docs",
    "get_submitted_linked_docs",
    "get_naming_series_preview",
    # Tier 3 desk-mirror actions: parity with the buttons a Desk user
    # can click - email, comment, share, assign, tag, follow. All
    # mutating; descriptors in tool-defs.ts carry ALWAYS-CONFIRM
    # language for the side-effectful ones.
    "send_email",
    "add_comment",
    "update_comment",
    "share_doc",
    "unshare_doc",
    "assign_to",
    "unassign_from",
    "add_tag",
    "remove_tag",
    "follow_document",
    "unfollow_document",
)


def _resolve(name: str) -> Callable:
    mod = importlib.import_module(f"jarvis.tools.{name}")
    return getattr(mod, name)


_TOOLS: dict[str, Callable] = {name: _resolve(name) for name in _TOOL_NAMES}


def _accepted_params(fn: Callable) -> set[str]:
    """Names of the parameters ``fn`` is willing to bind by keyword.

    Computed once per tool function and cached so dispatch doesn't pay
    the inspect cost on every call. If a tool ever uses ``**kwargs``
    we surface that with an empty set + a special VAR_KEYWORD marker
    via the cache (caller skips filtering for those tools).
    """
    return {
        p.name
        for p in inspect.signature(fn).parameters.values()
        if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    }


_ACCEPTS_VAR_KW: dict[str, bool] = {
    name: any(
        p.kind == p.VAR_KEYWORD for p in inspect.signature(fn).parameters.values()
    )
    for name, fn in _TOOLS.items()
}
_ACCEPTED_PARAMS: dict[str, set[str]] = {
    name: _accepted_params(fn) for name, fn in _TOOLS.items()
}


def list_tools() -> list[str]:
    return sorted(_TOOLS.keys())


def dispatch(tool_name: str, args: dict):
    if tool_name not in _TOOLS:
        raise ToolNotFoundError(f"no such tool: {tool_name}")
    if not isinstance(args, dict):
        raise InvalidArgumentError("args must be a dict")
    # Filter args to keys the tool's signature actually binds. Defense-
    # in-depth against an LLM that hallucinates extra keyword args - a
    # tool that does ``def get_doc(doctype, name)`` should not receive a
    # ``permission_check=False`` kwarg even if the LLM emits one.
    # ``api._parse_args`` already strips the legacy ``_user``/``_session``
    # markers; this is the wider allowlist over what the tool's own
    # parameter list declares. Tools that use ``**kwargs`` opt out
    # (currently none, but future tools wanting bag-of-args semantics
    # would skip the filter naturally).
    if not _ACCEPTS_VAR_KW.get(tool_name, False):
        accepted = _ACCEPTED_PARAMS[tool_name]
        args = {k: v for k, v in args.items() if k in accepted}
    try:
        return _TOOLS[tool_name](**args)
    except TypeError as e:
        raise InvalidArgumentError(str(e))
