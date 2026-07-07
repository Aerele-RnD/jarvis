"""Scope visibility + human write matrix for ``Jarvis Wiki Page`` (wiki v2).

Visibility (read) — enforced everywhere (Desk lists via the
``permission_query_conditions`` hook, per-doc access via the
``has_permission`` hook, SPA/tool queries via ``visible_scope_condition``):

  * Org pages (scope NULL/empty counts as Org): every desk user.
  * Role pages: users holding ``target_role`` (+ System Manager).
  * User pages: ``target_user`` only (+ System Manager).

Human write matrix (SPA create/save/archive; Desk edits are role-perm
limited to System Manager anyway):

  * Org: System Manager only.
  * Role: Knowledge Wiki Manager holding that role, or SM (any role).
  * User: the target user themselves when they hold Knowledge Wiki
    User/Manager, or SM.

The LLM channel (``update_wiki`` tool + ingest) deliberately bypasses this
matrix for Org pages — any desk user feeds the org wiki through the
confirm-gated, sanitized pipeline; those writers use ``ignore_permissions``
with explicit channel checks (see jarvis/chat/wiki.py).

NOTE on the has_permission hook: on this Frappe version controller hooks can
only DENY — any falsy return (None included) denies, so this module returns
an explicit True to defer to the normal role-perm check.
"""

from __future__ import annotations

import frappe

WIKI = "Jarvis Wiki Page"

WIKI_USER_ROLE = "Knowledge Wiki User"
WIKI_MANAGER_ROLE = "Knowledge Wiki Manager"

# Never offered as a Role-scope audience (mirrors agents_api's selectable set).
_NON_TARGETABLE_ROLES = ("Administrator", "Guest", "All")

# ptypes that reveal page content; everything read-shaped maps to visibility.
_READ_PTYPES = ("read", "select", "print", "email", "export", "share", "report")


def _is_sm(user: str) -> bool:
	# Administrator's get_roles returns every Role, so the explicit check is
	# just a shortcut; both spellings of "full access" land here.
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _get(page, field: str):
	# dict rows (frappe.get_all) and Document both expose .get.
	return page.get(field)


def can_read_page(page, user: str | None = None) -> bool:
	"""Visibility matrix for one page (dict with scope/target_* fields, or a
	Document)."""
	user = user or frappe.session.user
	if _is_sm(user):
		return True
	scope = (_get(page, "scope") or "").strip() or "Org"
	if scope == "Org":
		return True
	if scope == "Role":
		target_role = _get(page, "target_role")
		return bool(target_role) and target_role in frappe.get_roles(user)
	if scope == "User":
		return (_get(page, "target_user") or "") == user
	return False


def can_edit_page(page, user: str | None = None) -> bool:
	"""Human-channel write matrix (create/modify). The LLM channel's Org
	writes bypass this by design — see the module docstring."""
	user = user or frappe.session.user
	if _is_sm(user):
		return True
	scope = (_get(page, "scope") or "").strip() or "Org"
	roles = set(frappe.get_roles(user))
	if scope == "Role":
		target_role = _get(page, "target_role")
		return (
			WIKI_MANAGER_ROLE in roles
			and bool(target_role)
			and target_role in roles
		)
	if scope == "User":
		return (_get(page, "target_user") or "") == user and bool(
			roles & {WIKI_USER_ROLE, WIKI_MANAGER_ROLE}
		)
	# Org pages: System Manager only.
	return False


def can_archive_page(page, user: str | None = None) -> bool:
	"""Archive shares the edit matrix (archive is a status flip through save)."""
	return can_edit_page(page, user)


def creatable_scopes(user: str | None = None) -> list[str]:
	"""Scopes this user may create pages in (subset of Org/Role/User).
	Plain desk users get [] — their wiki writes flow through the LLM channel."""
	user = user or frappe.session.user
	if _is_sm(user):
		return ["Org", "Role", "User"]
	roles = set(frappe.get_roles(user))
	out: list[str] = []
	if WIKI_MANAGER_ROLE in roles:
		out.append("Role")
	if roles & {WIKI_USER_ROLE, WIKI_MANAGER_ROLE}:
		out.append("User")
	return out


def manageable_roles(user: str | None = None) -> list[str]:
	"""Roles the user may target for Role-scope pages: a Knowledge Wiki
	Manager targets roles they hold; SM targets any enabled desk role."""
	user = user or frappe.session.user
	if _is_sm(user):
		return [
			r
			for r in frappe.get_all(
				"Role",
				filters={"disabled": 0, "desk_access": 1},
				order_by="name asc",
				pluck="name",
			)
			if r not in _NON_TARGETABLE_ROLES
		]
	if WIKI_MANAGER_ROLE not in frappe.get_roles(user):
		return []
	return sorted(set(frappe.get_roles(user)) - set(_NON_TARGETABLE_ROLES))


def visible_scope_condition(user: str | None = None) -> str:
	"""SQL boolean fragment over ``tabJarvis Wiki Page`` implementing the
	visibility matrix; always a parenthesized valid expression so callers can
	splice it with ``and``. Values go through frappe.db.escape — role names
	and user emails are org-author-controlled strings."""
	user = user or frappe.session.user
	if _is_sm(user):
		return "(1=1)"
	table = "`tabJarvis Wiki Page`"
	clauses = [f"coalesce({table}.`scope`, '') in ('', 'Org')"]
	roles = [r for r in frappe.get_roles(user) if r]
	if roles:
		role_list = ", ".join(frappe.db.escape(r) for r in roles)
		clauses.append(
			f"({table}.`scope` = 'Role' and {table}.`target_role` in ({role_list}))"
		)
	clauses.append(
		f"({table}.`scope` = 'User' and {table}.`target_user` = {frappe.db.escape(user)})"
	)
	return "(" + " or ".join(clauses) + ")"


def wiki_page_query_conditions(user: str | None = None) -> str:
	"""hooks.permission_query_conditions entry — scopes every Desk/ORM list
	query. Empty string (no restriction) for System Managers."""
	user = user or frappe.session.user
	if _is_sm(user):
		return ""
	return visible_scope_condition(user)


def has_wiki_page_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	"""hooks.has_permission entry — per-doc gate. Read-shaped ptypes follow
	the visibility matrix, write follows the edit matrix, delete stays SM.
	True defers to the role-perm check (hooks can only deny)."""
	user = user or frappe.session.user
	if ptype in _READ_PTYPES:
		return can_read_page(doc, user)
	if ptype == "write":
		return can_edit_page(doc, user)
	if ptype == "delete":
		return _is_sm(user)
	return True
