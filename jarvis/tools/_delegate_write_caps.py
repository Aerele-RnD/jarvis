"""R5-J9 — session-bound WRITE capabilities for delegate agents.

Codex R5-P0-04: the marketplace agents' declared ``writes[]`` were metadata only.
An operator (or an auditor) that received ``jarvis__create_doc`` / ``jarvis__update_doc``
could write ANY doctype the run-as user's ordinary Frappe roles allowed — the
manifest contract was never a runtime boundary, only a model instruction.

This module closes that seam. When a write tool runs OVER A DELEGATE RUN SESSION
(the pre-created ``Jarvis Agent Run`` whose ``session_key`` the plugin dispatcher
stashed on ``frappe.local`` — see ``_agent_run_ctx``), the write is bounded by the
agent's DECLARED contract, enforced BEFORE any Frappe permission check:

  * The caller's delegate identity is resolved the SAME way ``record_agent_run``
    resolves its run — ``Jarvis Agent Run.session_key == <caller session_key>``
    (never a model-supplied id, so a delegate can only ever act as its own run).
    A session with no bound Run is NOT a delegate: standard chat / macro / test
    callers are left completely untouched (``resolve_delegate`` returns None and
    the enforce_* helpers are no-ops).
  * AUDITORS (``writes`` null/empty) are refused every write outright.
  * OPERATORS may create/update ONLY a doctype declared in ``writes[]`` (with the
    operation, when a writes entry narrows it), ONLY while the target is a draft
    (``docstatus == 0``), and — for updates — ONLY a row OWNED BY the run-as
    identity. Everything else raises ``PermissionDeniedError``.

The ``writes[]`` contract is DECLARATIVE, non-IP (a list of ``{doctype, mode}``;
``mode`` ∈ {draft, approval-request}) mirrored from the bundle-store manifest —
never a rule body/threshold. Storage: ``Jarvis Agent Listing.writes`` (JSON),
populated by ``agent_catalog.sync_agent_listings``.
"""

import json

import frappe

from jarvis.exceptions import PermissionDeniedError
from jarvis.tools._agent_run_ctx import get_session_key

RUN = "Jarvis Agent Run"
LISTING = "Jarvis Agent Listing"


def _parse_writes(raw) -> list:
	"""The listing's ``writes`` JSON -> a list of ``{doctype, mode, ...}`` dicts.
	A malformed / non-list value is treated as an EMPTY contract (fail-closed:
	an operator with an unreadable contract writes nothing)."""
	if not raw:
		return []
	if isinstance(raw, list):
		parsed = raw
	else:
		try:
			parsed = json.loads(raw)
		except (TypeError, ValueError):
			return []
	return [w for w in parsed if isinstance(w, dict) and w.get("doctype")] if isinstance(parsed, list) else []


def resolve_delegate() -> dict | None:
	"""The delegate capability for the CURRENT tool call, or None when the caller
	is not a delegate (standard chat, macro, direct-Python, or a test that set no
	session_key).

	Delegate iff a ``Jarvis Agent Run`` row is bound to the caller's session_key
	(``Run.session_key`` only ever holds the ``agent:agent-<slug>:<run>`` shape a
	delegate launch mints, so the lookup itself is the discriminator — a normal
	chat session_key never matches). ``run_as`` is the impersonated identity the
	dispatcher already switched the session to (``frappe.session.user``), i.e. the
	Run's run-as user — the ownership axis update enforcement gates on.

	Returns ``{agent, nature, writes, run_as}`` or None.
	"""
	session_key = get_session_key()
	if not session_key:
		return None
	run = frappe.db.get_value(
		RUN,
		{"session_key": session_key},
		["name", "agent"],
		as_dict=True,
	)
	if not run or not run.agent:
		return None  # no delegate run bound -> not a delegate; leave the caller untouched
	listing = frappe.db.get_value(LISTING, run.agent, ["nature", "writes"], as_dict=True) or {}
	return {
		"agent": run.agent,
		"nature": (listing.get("nature") or "").strip().lower(),
		"writes": _parse_writes(listing.get("writes")),
		"run_as": frappe.session.user,
	}


def _match(writes: list, doctype: str, operation: str) -> dict | None:
	"""The declared ``writes[]`` entry authorising ``operation`` on ``doctype``, or
	None. Matches doctype exactly; an entry MAY narrow the allowed operation via an
	optional ``operation`` (str) or ``operations`` (list) key — absent means the
	declared doctype permits both create and update (the manifest today carries only
	``{doctype, mode}``, so both are allowed for a declared doctype)."""
	for w in writes:
		if w.get("doctype") != doctype:
			continue
		ops = w.get("operations") or w.get("operation")
		if ops is None:
			return w  # unrestricted: both create + update allowed for this doctype
		if isinstance(ops, str):
			ops = [ops]
		if operation in {str(o).strip().lower() for o in ops}:
			return w
	return None


def _refuse_non_operator(cap: dict, operation: str, doctype: str) -> None:
	"""Refuse a write from a caller that is not a write-capable operator (an auditor,
	or an operator whose contract is empty). Raised BEFORE Frappe permission checks."""
	if cap["nature"] != "operator" or not cap["writes"]:
		raise PermissionDeniedError(
			f"agent '{cap['agent']}' is not permitted to {operation} documents "
			f"(no declared write capability); refusing {doctype}"
		)


def enforce_create(doctype: str) -> None:
	"""R5-J9 gate for a delegate create. No-op for non-delegate callers. A create is
	inherently a draft (``docstatus`` is a refused protected field on the way in), so
	the docstatus==0 constraint is structural; there is no owner constraint on create."""
	cap = resolve_delegate()
	if cap is None:
		return
	_refuse_non_operator(cap, "create", doctype)
	if _match(cap["writes"], doctype, "create") is None:
		raise PermissionDeniedError(
			f"agent '{cap['agent']}' may not create '{doctype}' — it is not in the "
			f"agent's declared write contract"
		)


def enforce_update(doctype: str, name: str) -> None:
	"""R5-J9 gate for a delegate update. No-op for non-delegate callers. An operator
	may update ONLY a declared doctype, ONLY a draft (``docstatus == 0``), and ONLY a
	row it owns (the run-as identity). Enforced BEFORE Frappe permission checks — the
	docstatus/owner probe uses a permission-agnostic ``db.get_value`` so the contract
	boundary is decided independently of the run-as user's roles."""
	cap = resolve_delegate()
	if cap is None:
		return
	_refuse_non_operator(cap, "update", doctype)
	if _match(cap["writes"], doctype, "update") is None:
		raise PermissionDeniedError(
			f"agent '{cap['agent']}' may not update '{doctype}' — it is not in the "
			f"agent's declared write contract"
		)
	row = frappe.db.get_value(doctype, name, ["docstatus", "owner"], as_dict=True)
	if row is None:
		# The doc does not exist; defer to update_doc's own get_doc, which raises a
		# clearer DoesNotExistError. Nothing to bound here.
		return
	if frappe.utils.cint(row.docstatus) != 0:
		raise PermissionDeniedError(
			f"agent '{cap['agent']}' may only update DRAFT documents; "
			f"{doctype} '{name}' is submitted/cancelled (docstatus {row.docstatus})"
		)
	if row.owner != cap["run_as"]:
		raise PermissionDeniedError(
			f"agent '{cap['agent']}' may only update documents it created; "
			f"{doctype} '{name}' is owned by another identity"
		)
