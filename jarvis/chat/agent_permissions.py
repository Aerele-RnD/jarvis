"""Row-level ownership scoping for the Jarvis agent doctypes (security review
PART 3, TASK 29).

The data-layer twin of ``jarvis/chat/chat_permissions.py`` for the four
owner/installer-scoped agent doctypes:

  * Jarvis Agent Installation -> the row's own ``owner`` (the installer).
  * Jarvis Agent Run          -> the row's own ``owner``.
  * Jarvis Agent Finding      -> the row's own ``owner``.
  * Jarvis Agent Activity     -> the row's own ``owner``.

Runs / findings / activity are inserted server-side (``ignore_permissions``) by
the audit engine and then handed to the installation owner via a raw
``db.set_value(..., "owner", owner)`` reassignment (``agent_runs.py`` /
``agent_scheduler.py``), so the row's own ``owner`` is always the installer — a
reliable single axis. Findings/runs can carry sensitive audit output, so this
keeps them owner-or-SM scoped even over generic REST.

The catalog doctype ``Jarvis Agent Listing`` is deliberately NOT scoped here: it
is a shared vendor catalog readable by every Jarvis User (its perm row stays
read-for-all). Its proprietary ``skill_bundle`` field is protected by a
permlevel-1 grant (TASK 33) instead of an owner hook.

System Manager (and Administrator) get org-wide READ (oversight; the existing SM
perm rows are the base grant). ``Administrator`` bypasses Frappe perms entirely.

Every interpolated value goes through ``frappe.db.escape``.

NOTE (hooks can only DENY): a falsy ``has_permission`` return denies, so every
allow path returns an explicit ``True`` to defer to the normal role-perm check.
"""

from __future__ import annotations

import frappe

INSTALLATION = "Jarvis Agent Installation"
RUN = "Jarvis Agent Run"
FINDING = "Jarvis Agent Finding"
ACTIVITY = "Jarvis Agent Activity"


def _is_sm(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _owner_query(table: str, user: str | None) -> str:
	user = user or frappe.session.user
	if _is_sm(user):
		return ""
	return f"`tab{table}`.`owner` = {frappe.db.escape(user)}"


def _owner_has_permission(doc, ptype: str, user: str | None) -> bool:
	user = user or frappe.session.user
	if _is_sm(user):
		return True
	if ptype == "create":
		# ``owner`` is assigned by Frappe / reassigned to the installer by the
		# engine; the role + ``if_owner`` rule governs create.
		return True
	return doc.get("owner") == user


# --------------------------------------------------------------------------- #
# Jarvis Agent Installation
# --------------------------------------------------------------------------- #
def installation_query_conditions(user: str | None = None) -> str:
	return _owner_query(INSTALLATION, user)


def has_installation_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	return _owner_has_permission(doc, ptype, user)


# --------------------------------------------------------------------------- #
# Jarvis Agent Run
# --------------------------------------------------------------------------- #
def run_query_conditions(user: str | None = None) -> str:
	return _owner_query(RUN, user)


def has_run_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	return _owner_has_permission(doc, ptype, user)


# --------------------------------------------------------------------------- #
# Jarvis Agent Finding
# --------------------------------------------------------------------------- #
def finding_query_conditions(user: str | None = None) -> str:
	return _owner_query(FINDING, user)


def has_finding_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	return _owner_has_permission(doc, ptype, user)


# --------------------------------------------------------------------------- #
# Jarvis Agent Activity
# --------------------------------------------------------------------------- #
def activity_query_conditions(user: str | None = None) -> str:
	return _owner_query(ACTIVITY, user)


def has_activity_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	return _owner_has_permission(doc, ptype, user)
