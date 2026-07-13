"""Row-level ownership scoping for the Jarvis macro doctypes (Jarvis Macro,
Jarvis Macro Run) — security review PART 3, TASK 23/24.

The data-layer twin of ``jarvis/chat/chat_permissions.py``: list / report /
generic-REST queries are scoped via ``permission_query_conditions`` and per-doc
read/write/create/delete via ``has_permission`` — both registered in
``hooks.py``. Together with putting the ``Jarvis User`` role (not ``role:
"All"``) on the doctype permission rows, this makes the role genuinely
load-bearing (a Website/portal user, categorically denied Jarvis, can no longer
``POST /api/resource/Jarvis Macro`` and have the scheduler run it) and closes
the Macro-Run create-inject at the ORM.

Ownership axes:

  * Jarvis Macro     -> the row's own ``owner`` (the creator). Matches the
    ``if_owner`` perm rule that also stays on the doctype.
  * Jarvis Macro Run -> the row's own ``owner`` too. A run is inserted server
    side (``macros.run_macro`` with ``ignore_permissions``) and its owner is
    reassigned to the MACRO's owner by construction (``macros.py``: the
    ``_reassign_owner`` handoff), so scoping by the run's own owner is exactly
    the macro-owner axis. On CREATE (the only path a generic-REST insert can
    reach — legit runs bypass this hook via ``ignore_permissions``) the hook
    additionally rejects a run whose linked ``macro`` (or ``conversation``, if
    set) is not owned by the caller (MAC-2 cross-inject guard).

System Manager gets org-wide READ (oversight; the SM perm rows added to both
doctypes are read-only, mirroring ``Jarvis Voice Note``). ``Administrator``
bypasses Frappe perms entirely; every function guards for it via ``_is_sm``.

Every interpolated value in a SQL fragment goes through ``frappe.db.escape``.

NOTE (hooks can only DENY): a falsy ``has_permission`` return denies, so every
allow path returns an explicit ``True`` to defer to the normal role-perm check.
"""

from __future__ import annotations

import frappe

MACRO = "Jarvis Macro"
MACRO_RUN = "Jarvis Macro Run"
CONVERSATION = "Jarvis Conversation"


def _is_sm(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


# --------------------------------------------------------------------------- #
# Jarvis Macro - the row's own owner is the axis (matches ``if_owner``).
# --------------------------------------------------------------------------- #
def macro_query_conditions(user: str | None = None) -> str:
	"""Scope every list/report/REST query on Jarvis Macro to the caller's own
	rows. System Manager (and Administrator) get org-wide READ (oversight)."""
	user = user or frappe.session.user
	if _is_sm(user):
		return ""
	return f"`tab{MACRO}`.`owner` = {frappe.db.escape(user)}"


def has_macro_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	user = user or frappe.session.user
	if _is_sm(user):
		return True
	if ptype == "create":
		# ``owner`` is assigned by Frappe during insert (creator == owner); the
		# role + ``if_owner`` rule governs create. Enforcing owner here would race
		# the owner assignment.
		return True
	return doc.get("owner") == user


# --------------------------------------------------------------------------- #
# Jarvis Macro Run - the row's own owner (= the macro owner by construction).
# --------------------------------------------------------------------------- #
def macro_run_query_conditions(user: str | None = None) -> str:
	"""Scope Jarvis Macro Run queries to the caller's own rows. System Manager
	(and Administrator) get org-wide READ."""
	user = user or frappe.session.user
	if _is_sm(user):
		return ""
	return f"`tab{MACRO_RUN}`.`owner` = {frappe.db.escape(user)}"


def has_macro_run_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	"""Per-doc gate for Jarvis Macro Run. Read/write/delete: own-owner axis. On
	CREATE (MAC-2): reject a run whose linked ``macro`` (or ``conversation``, if
	set) is not owned by the caller, so a generic-REST insert cannot attach a run
	to another user's macro. Legit runs are inserted server-side with
	``ignore_permissions`` and never consult this hook."""
	user = user or frappe.session.user
	if _is_sm(user):
		return True
	if ptype == "create":
		macro = doc.get("macro")
		if macro and frappe.db.get_value(MACRO, macro, "owner") != user:
			return False
		conv = doc.get("conversation")
		if conv and frappe.db.get_value(CONVERSATION, conv, "owner") != user:
			return False
		return True
	return doc.get("owner") == user
