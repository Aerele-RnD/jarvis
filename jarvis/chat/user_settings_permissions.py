"""``user``-keyed row scoping for ``Jarvis User Settings`` (security review
PART 4 REVISED, TASK 52).

``Jarvis User Settings`` (introduced by #278) is the per-user chat-prefs + usage
doctype. Its permission rows were ``role:"All"`` + ``if_owner`` with NO ORM hook
— the exact anti-pattern Parts 1–3 eliminated: ``role:"All"`` admits
Website/portal users (PART 1 TASK 6), and the scoping rode purely on the
``owner`` axis while the whitelisted API (``chat/user_settings_api.py``) scopes on
the ``user`` field (owner/user-drift risk, PART 2 TASK 17).

This hook keys the ORM scoping on the **``user``** field so generic REST
list/get matches the API's ``user``-based scoping and survives any owner/user
drift. The doctype ``All`` rows are now ``Jarvis User`` (the role is
load-bearing), and the **admin tier** (System Manager / Jarvis Admin /
Administrator) is unrestricted — the admin usage board
(``user_settings_api.admin_list_user_usage``) reads every user's row via a
permission-checked ``frappe.get_all``, so the query hook MUST return "" for an
admin or that board would collapse to the admin's own row.

Mirrors ``jarvis/chat/personalise_permissions.py`` (which is SM-only
unrestricted); this one widens the unrestricted tier to the Jarvis-Admin
management tier because per-user usage administration is a Jarvis-Admin surface.

NOTE (hooks can only DENY): a falsy ``has_permission`` return denies, so every
allow path returns an explicit ``True`` to defer to the normal role-perm check.
"""

from __future__ import annotations

import frappe

from jarvis.permissions import has_jarvis_admin_access

USER_SETTINGS = "Jarvis User Settings"


def user_settings_query_conditions(user: str | None = None) -> str:
	"""Scope every list/report/REST query on Jarvis User Settings to the caller's
	own row, keyed on the ``user`` field (not ``owner``). The admin tier
	(System Manager / Jarvis Admin / Administrator) is unrestricted — the
	admin usage board reads all rows via a permission-checked ``frappe.get_all``."""
	user = user or frappe.session.user
	if has_jarvis_admin_access(user):
		return ""
	return f"`tabJarvis User Settings`.`user` = {frappe.db.escape(user)}"


def has_user_settings_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	"""Per-doc gate keyed on the ``user`` field. Admin tier: all. Everyone else:
	only the row whose ``user`` is them. Create of a row targeting another user is
	denied (the usage worker inserts with ignore_permissions and skips this hook)."""
	user = user or frappe.session.user
	if has_jarvis_admin_access(user):
		return True
	target = doc.get("user")
	if ptype == "create":
		# A settings row must target the creator; backend usage writers (running
		# as Administrator / the worker) insert with ignore_permissions and skip
		# this hook entirely.
		return target is None or target == user
	return target == user
