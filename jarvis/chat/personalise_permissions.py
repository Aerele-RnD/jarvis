"""``user``-keyed row scoping for ``Jarvis Personalise Question`` (security
review PART 2, TASK 17).

The app API scopes a user's question bank on the **``user``** field, while the
generic Frappe REST surface scopes on **``owner``** (the doctype's ``if_owner``
rule). Equality of the two relies solely on the ``before_insert`` owner-stamp
(``jarvis_personalise_question.py``: ``self.owner = self.user``). Any future
write path that sets ``user`` without going through that stamp (a raw
``frappe.db`` insert, a bulk ``set_value``) would let ``owner`` and ``user``
diverge, and the two access channels would then disagree about which rows a
user sees.

This hook keys the ORM scoping on the **``user``** field too, so generic REST
list/get matches the API's ``user``-based scoping and survives any owner/user
drift. Mirrors ``jarvis/chat/wiki_permissions.py`` / ``chat_permissions.py``.

NOTE (hooks can only DENY): a falsy ``has_permission`` return denies, so every
allow path returns an explicit ``True`` to defer to the normal role-perm check.
"""

from __future__ import annotations

import frappe

QUESTION = "Jarvis Personalise Question"


def _is_sm(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def personalise_question_query_conditions(user: str | None = None) -> str:
	"""Scope every list/report/REST query on Jarvis Personalise Question to the
	caller's own rows, keyed on the ``user`` field (not ``owner``). System
	Manager (and Administrator) are unrestricted (the existing SM perm row)."""
	user = user or frappe.session.user
	if _is_sm(user):
		return ""
	return f"`tabJarvis Personalise Question`.`user` = {frappe.db.escape(user)}"


def has_personalise_question_permission(doc, ptype: str = "read", user: str | None = None) -> bool:
	"""Per-doc gate keyed on the ``user`` field. System Manager: all. Everyone
	else: only rows whose ``user`` is them. Create of a row targeting another
	user is denied (the materializer inserts with ignore_permissions)."""
	user = user or frappe.session.user
	if _is_sm(user):
		return True
	target = doc.get("user")
	if ptype == "create":
		# A question must target the creator; backend materializers (running as
		# Administrator / the engine) insert with ignore_permissions and skip
		# this hook entirely.
		return target is None or target == user
	return target == user
