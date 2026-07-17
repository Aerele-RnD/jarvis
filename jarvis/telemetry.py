"""Read-path tool + turn telemetry for customization discovery (stage 4).

Structured JSON lines to a dedicated logger, mirroring jarvis/audit.py's
never-raise contract (audit covers WRITE tools; this covers the discovery
read path). Two line kinds:

  {"kind": "tool", ts, site, user_hash, conversation, tool, duration_ms,
   result_chars, custom_target}
  {"kind": "turn", ts, site, conversation, run_id, duration_ms,
   touched_custom}

Emitted for (a) every describe_customizations call and (b) any
get_schema/query/get_list call whose target doctype is one of the site's
custom doctypes (``custom_target: true`` - these also flag the turn). Plus
one line per completed chat turn. jarvis/site_profile/analyze.py reads these
to compute the activation rate: did the agent consult the index before its
first custom-entity touch? Telemetry must never break a tool call or a turn:
every public function swallows everything.
"""

from __future__ import annotations

import hashlib
import json

import frappe

_LOGGER = "jarvis.tool_telemetry"
_TRACKED_TARGET_TOOLS = frozenset({"get_schema", "query", "get_list"})
_TRACKED_TOOL = "describe_customizations"

# Custom-doctype name set (both unions), cached per site; invalidated by the
# same schema doc_events as the customizations clause (clear_clause_cache
# deletes this key too) with the TTL as backstop.
DOCTYPE_SET_CACHE_KEY = "jarvis:telemetry_custom_doctypes"
_DOCTYPE_SET_TTL_S = 300

_TURN_FLAG_TTL_S = 3600


def record_tool(tool: str, args, conversation: str | None,
		duration_ms: int, result) -> None:
	"""One line per relevant tool call, from api._run_tool. Fast no-op for
	every untracked tool; never raises."""
	try:
		custom_target = False
		if tool == _TRACKED_TOOL:
			pass
		elif tool in _TRACKED_TARGET_TOOLS:
			doctype = args.get("doctype") if isinstance(args, dict) else None
			if not doctype or doctype not in custom_doctype_set():
				return
			custom_target = True
			if conversation:
				_mark_turn_custom(conversation)
		else:
			return
		_emit({
			"kind": "tool",
			"ts": frappe.utils.now(),
			"site": getattr(frappe.local, "site", None),
			"user_hash": _user_hash(frappe.session.user),
			"conversation": conversation,
			"tool": tool,
			"duration_ms": int(duration_ms),
			"result_chars": _result_chars(result),
			"custom_target": custom_target,
		})
	except Exception:
		pass


def emit_turn(conversation: str | None, run_id: str | None,
		duration_ms: int) -> None:
	"""One line per completed chat turn (turn_handler's finalize point),
	carrying whether any tool call in it touched a custom doctype. Reads AND
	clears the per-turn flag; never raises."""
	try:
		if not conversation:
			return
		_emit({
			"kind": "turn",
			"ts": frappe.utils.now(),
			"site": getattr(frappe.local, "site", None),
			"conversation": conversation,
			"run_id": run_id,
			"duration_ms": int(duration_ms),
			"touched_custom": _read_and_clear_turn_flag(conversation),
		})
	except Exception:
		pass


def custom_doctype_set() -> frozenset:
	"""Names of the site's custom doctypes (custom=1 UNION module->custom
	app), cached. Empty set on any failure - telemetry then under-reports
	rather than erroring."""
	try:
		cache = frappe.cache()
		cached = cache.get_value(DOCTYPE_SET_CACHE_KEY)
		if cached is not None:
			return frozenset(cached)
		from jarvis.site_profile import apps as sp_apps

		names = set(frappe.get_all("DocType", filters={"custom": 1}, pluck="name"))
		modules = sp_apps.custom_module_names()
		if modules:
			names |= set(frappe.get_all(
				"DocType", filters={"module": ("in", list(modules))}, pluck="name"))
		cache.set_value(
			DOCTYPE_SET_CACHE_KEY, sorted(names), expires_in_sec=_DOCTYPE_SET_TTL_S)
		return frozenset(names)
	except Exception:
		return frozenset()


def _turn_flag_key(conversation: str) -> str:
	return f"jarvis:turn_custom:{conversation}"


def _mark_turn_custom(conversation: str) -> None:
	try:
		frappe.cache().set_value(
			_turn_flag_key(conversation), 1, expires_in_sec=_TURN_FLAG_TTL_S)
	except Exception:
		pass


def _read_and_clear_turn_flag(conversation: str) -> bool:
	try:
		cache = frappe.cache()
		key = _turn_flag_key(conversation)
		flag = cache.get_value(key)
		if flag:
			cache.delete_value(key)
		return bool(flag)
	except Exception:
		return False


def _user_hash(user: str | None) -> str:
	return hashlib.sha1((user or "").encode()).hexdigest()[:12]


def _result_chars(result) -> int:
	try:
		return len(frappe.as_json(result))
	except Exception:
		return 0


def _emit(entry: dict) -> None:
	frappe.logger(_LOGGER).info(json.dumps(entry, default=str))
