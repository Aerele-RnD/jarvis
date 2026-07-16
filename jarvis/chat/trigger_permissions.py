"""ORM-level permission hooks for Jarvis Trigger.

The data-layer twin of ``jarvis/chat/macro_permissions.py``, registered in
hooks.py via ``permission_query_conditions`` / ``has_permission``. Triggers
are org-visible automation (NOT owner-scoped): any jarvis user may READ every
trigger (the doctype rows grant ``Jarvis User`` read), but write/create/delete
are reserved for System Manager / Jarvis Admin — the same tier the doctype
permission rows grant, re-asserted here so a future perm-row edit cannot
silently widen the manage surface via generic REST.

``Jarvis Trigger Activity`` deliberately has NO hooks: its doctype perms are
System Manager-only and ``jarvis.chat.triggers_api.list_activity_page`` serves
visibility-filtered rows (read access on the target doc) to everyone else.

NOTE (hooks can only DENY): a falsy ``has_permission`` return denies, so every
allow path returns an explicit ``True`` to defer to the normal role-perm check.
"""

from __future__ import annotations

import frappe

from jarvis.permissions import has_jarvis_admin_access

# Only the manage verbs are tier-gated; read/select/report/etc. defer to the
# doctype permission rows (denying e.g. "select" here would break link-field
# searches for plain Jarvis Users).
_MANAGE_PTYPES = ("write", "create", "delete")


def trigger_query_conditions(user: str | None = None) -> str:
	"""No row scoping: every user the role perms let in sees every trigger."""
	return ""


def has_trigger_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	"""Per-doc gate: manage verbs need System Manager / Jarvis Admin
	(Administrator implicit); everything else defers to role perms."""
	user = user or frappe.session.user
	if ptype in _MANAGE_PTYPES:
		return has_jarvis_admin_access(user)
	return True
