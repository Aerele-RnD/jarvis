"""Single source of truth for the Jarvis app-access gate.

Reaching Jarvis at all requires the dedicated ``Jarvis User`` role, with
``System Manager`` always allowed and ``Administrator`` implicitly allowed
(it bypasses all perms).

Enforcement is at the HUMAN ENTRY POINTS — the SPA route (``www/jarvis.py``),
the desk page (``jarvis_chat``) and the user-initiated chat APIs. It is
deliberately NOT applied to machine-authenticated or delegated paths (the
self-hosted plugin tool user, or ``send_message`` invoked under
``set_user(owner)`` by the scheduler / approvals resume), which act as an
identity that legitimately may not hold the role.
"""

from __future__ import annotations

import functools
from contextlib import contextmanager

import frappe

# The role name + the access rule, everywhere: "Jarvis User" OR "System Manager"
# (Administrator is implicitly allowed by has_jarvis_access / frappe perms).
# One constant so the seed (learning/roles.py, the grant patch, tests) and the
# gate can never drift.
JARVIS_USER_ROLE = "Jarvis User"
JARVIS_ACCESS_ROLES = ("System Manager", JARVIS_USER_ROLE)

# Reviewer set authorized for org-wide skill / pattern / wiki effects (security
# review PART 2, TASK 15 — RATIFIED). Housed in this lightweight module (no heavy
# imports) so the Jarvis Custom Skill controller / skill_permissions can import it
# without pulling in the learned_api import graph. Keep in sync with
# jarvis.chat.learned_api._REVIEWER_ROLES.
JARVIS_REVIEWER_ROLES = ("Jarvis Skill Reviewer", "Jarvis Admin", "System Manager")


def is_skill_reviewer(user: str | None = None) -> bool:
	"""True iff ``user`` may authorize org-wide skill effects: promote a Custom
	Skill up the User→Role→Org scope ladder, or apply skills bench-wide.
	``Administrator`` always passes. Defaults to the current session user."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(JARVIS_REVIEWER_ROLES) & set(frappe.get_roles(user)))


def require_skill_reviewer(user: str | None = None) -> None:
	"""Raise ``frappe.PermissionError`` unless ``user`` is a skill reviewer
	(Jarvis Skill Reviewer / Jarvis Admin / System Manager; Administrator
	implicit). Whitelisted endpoints call this to gate org-wide skill effects."""
	if not is_skill_reviewer(user):
		frappe.throw(
			"This action needs a Jarvis Skill Reviewer, Jarvis Admin or System "
			"Manager role.",
			frappe.PermissionError,
		)


def ensure_jarvis_user_role() -> None:
	"""Idempotently create the ``Jarvis User`` role (desk-access). Shared by the
	after_migrate seed and the one-time grant patch so the role definition lives
	in exactly one place."""
	if not frappe.db.exists("Role", JARVIS_USER_ROLE):
		frappe.get_doc({
			"doctype": "Role",
			"role_name": JARVIS_USER_ROLE,
			"desk_access": 1,
			"is_custom": 1,
		}).insert(ignore_permissions=True)


def has_jarvis_access(user: str | None = None) -> bool:
	"""True iff ``user`` may reach Jarvis.

	``Administrator`` is always allowed; otherwise the user must be a **System
	User** (never a Website/portal user - PART 1 TASK 6: portal users are a
	distinct, lower-trust population and must not reach chat) AND hold at least
	one of :data:`JARVIS_ACCESS_ROLES`. Defaults to the current session user."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	if not is_system_user(user):
		return False
	return bool(set(JARVIS_ACCESS_ROLES) & set(frappe.get_roles(user)))


def is_system_user(user: str | None = None) -> bool:
	"""True iff ``user`` is a Desk (System User), not a Website/portal user.
	``Administrator`` counts. Defaults to the current session user."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	if not user or user == "Guest":
		return False
	return frappe.db.get_value("User", user, "user_type") == "System User"


def require_jarvis_access(user: str | None = None) -> None:
	"""Raise ``frappe.PermissionError`` (with a clear message) if the user lacks
	access. Defaults to the current session user.

	Note: implemented directly rather than via ``frappe.only_for`` — in this
	Frappe version ``only_for`` treats its ``message`` argument as a boolean flag
	and would discard a custom string, showing a generic desk-role error."""
	if not has_jarvis_access(user):
		frappe.throw(
			"You need the Jarvis User role to use Jarvis. Ask an administrator for access.",
			frappe.PermissionError,
		)


def require_jarvis_user(fn):
	"""Decorator form of :func:`require_jarvis_access` for whitelisted chat
	endpoints (PART 1 TASK 8).

	Replaces the per-function ``require_jarvis_access()`` call convention with a
	single declarative marker so the ``test_chat_endpoint_gating`` coverage test
	can enumerate every ``@frappe.whitelist`` function under ``jarvis/chat/`` and
	assert each is either decorated or explicitly allowlisted - the "new endpoint
	forgot the gate" regression class can no longer slip through.

	Stack it BELOW ``@frappe.whitelist()`` (whitelist outermost) so Frappe
	registers the wrapper, and the gate runs before the body. ``functools.wraps``
	preserves the signature + annotations so Frappe's
	``require_type_annotated_api_methods`` still sees the real parameters.
	"""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		require_jarvis_access()
		return fn(*args, **kwargs)

	# Marker the coverage test reads (survives functools.wraps).
	wrapper.__jarvis_gated__ = True
	return wrapper


@contextmanager
def delegated_send():
	"""Mark the enclosed call stack as a TRUSTED server / delegated re-entry into
	``jarvis.chat.api.send_message`` (the scheduler, approval-resume, agent-run
	and File-Box drop paths), which run under ``impersonate(owner)`` where the
	impersonated owner legitimately may not hold the ``Jarvis User`` role.

	Uses ``frappe.flags`` (never an HTTP-settable parameter) so a browser POST
	cannot forge it. ``send_message`` reads this flag to (a) accept the call
	past its access gate and (b) insert the seed user message / touch the
	conversation with ``ignore_permissions`` so the now role-gated Message/
	Conversation create perms do not break the resume."""
	prev = frappe.flags.get("jarvis_delegated_send")
	frappe.flags.jarvis_delegated_send = True
	try:
		yield
	finally:
		frappe.flags.jarvis_delegated_send = prev
