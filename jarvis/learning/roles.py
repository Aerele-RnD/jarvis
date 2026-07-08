"""Computed role attachment for pattern learning (plan sections 4.1, 6.6).

Role tags on a learned pattern are DERIVED, never hardcoded: a role is attached
to a doctype iff it holds an org-wide (permlevel 0, not if_owner) read grant on
that doctype. ``get_all_perms`` already implements the Custom-DocPerm-replaces-
standard rule, so we read straight off it.

Two consumers:
  * the executor stamps ``roles_for_doctype(spec.doctype)`` onto every candidate
    (falls back to the spec's declared ``role_priors`` if this ever fails);
  * the compiler unions the compiled patterns' role sets into each learned
    skill's ``allowed_roles``; ``turn_handler`` intersects
    ``roles_for_user(chat_user)`` with those to decide activation.

Both are short-cached in redis (roles/perms change rarely and a stale minute is
harmless); the cache is bypassed under ``frappe.flags.in_test`` so a test that
mutates roles/perms inside its rolled-back transaction sees fresh results.
``roles_for_user`` rides ``frappe.get_roles`` (itself redis-cached per user), so
it is cheap enough for the chat hot path.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from jarvis.permissions import JARVIS_USER_ROLE, ensure_jarvis_user_role

_DT_CACHE_KEY = "jarvis_learning_roles_for_doctype"
_CACHE_TTL_S = 300


def roles_for_doctype(doctype: str) -> list[str]:
	"""Enabled, desk-access roles with an org-wide permlevel-0 read on ``doctype``.

	Excludes: disabled roles, portal roles (``desk_access=0`` never reach Desk
	data), and if_owner-only grants (a per-owner read is not org-wide, so it is
	not a delivery signal for a bench-global learned skill). Deterministic,
	sorted. Empty on any failure (the caller falls back to declared priors)."""
	if not doctype:
		return []

	use_cache = not frappe.flags.in_test
	if use_cache:
		try:
			cached = frappe.cache().hget(_DT_CACHE_KEY, doctype)
			if cached is not None:
				return list(cached)
		except Exception:
			pass

	result = _compute_roles_for_doctype(doctype)

	if use_cache:
		try:
			frappe.cache().hset(_DT_CACHE_KEY, doctype, result)
			# Bound staleness even if the hash is never explicitly cleared.
			frappe.cache().expire(_make_key(_DT_CACHE_KEY), _CACHE_TTL_S)
		except Exception:
			pass
	return result


def _compute_roles_for_doctype(doctype: str) -> list[str]:
	from frappe.permissions import get_all_perms

	try:
		roles = frappe.get_all(
			"Role",
			filters={"disabled": 0},
			fields=["name", "desk_access"],
		)
	except Exception:
		return []

	out: set[str] = set()
	for role in roles:
		name = role.get("name")
		if not name:
			continue
		# Portal roles (Customer/Supplier/Guest/...) never reach Desk data, so an
		# org-wide learned skill scoped to them is meaningless (plan section 4.1).
		if not cint(role.get("desk_access")):
			continue
		try:
			perms = get_all_perms(name) or []
		except Exception:
			continue
		if _grants_orgwide_read(perms, doctype):
			out.add(name)
	return sorted(out)


def _grants_orgwide_read(perms, doctype: str) -> bool:
	"""True iff any perm row grants read at permlevel 0 WITHOUT if_owner. A role
	whose only permlevel-0 read is if_owner=1 is per-owner, not org-wide, so it
	does not qualify (plan section 4.1)."""
	for p in perms:
		# get_all_perms rows are frappe._dict of DocPerm / Custom DocPerm fields.
		if (p.get("parent") == doctype
				and cint(p.get("permlevel")) == 0
				and cint(p.get("read"))
				and not cint(p.get("if_owner"))):
			return True
	return False


def roles_for_user(user: str | None = None) -> set[str]:
	"""The user's roles as a set (chat hot path). Rides ``frappe.get_roles``,
	which is redis-cached per user, so this is a cache read in the common case."""
	user = user or frappe.session.user
	try:
		return set(frappe.get_roles(user))
	except Exception:
		return set()


def clear_cache() -> None:
	"""Drop the doctype-role cache (call after a perms/role change; tests bypass
	the cache entirely via frappe.flags.in_test)."""
	try:
		frappe.cache().delete_value(_DT_CACHE_KEY)
	except Exception:
		pass


def _make_key(key: str) -> str:
	"""The site-namespaced redis key frappe.cache() actually writes for ``key``
	(hset stores under make_key(key)); used only to attach a TTL."""
	try:
		return frappe.cache().make_key(key)
	except Exception:
		return key


# --------------------------------------------------------------------------- #
# Wiki v2 role seeding (hooks.after_migrate)
# --------------------------------------------------------------------------- #
# The two human wiki-editing roles (matrix in jarvis/chat/wiki_permissions.py).
# Seeded on after_migrate because this app has no after_install channel and
# migrate follows a fresh install anyway (same reasoning as the voice_facts
# settings seeding). Pattern copied from jarvis_admin/install.py.
_WIKI_ROLES = ("Knowledge Wiki User", "Knowledge Wiki Manager")

def after_migrate() -> None:
	"""Idempotently create the Knowledge Wiki roles and the Jarvis User role
	(best-effort, never blocks a migrate)."""
	try:
		created = False
		for role_name in _WIKI_ROLES:
			if frappe.db.exists("Role", role_name):
				continue
			frappe.get_doc({
				"doctype": "Role", "role_name": role_name,
				"desk_access": 1, "is_custom": 0,
			}).insert(ignore_permissions=True)
			created = True
		# The app-access role — definition lives in jarvis/permissions.py (single
		# source of truth), seeded here so it exists before the grant patch runs.
		if not frappe.db.exists("Role", JARVIS_USER_ROLE):
			ensure_jarvis_user_role()
			created = True
		if created:
			frappe.db.commit()
	except Exception:
		frappe.log_error(
			title="jarvis wiki roles seed failed", message=frappe.get_traceback()
		)
