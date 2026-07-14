"""List-surface scoping for the GLOBAL ``File`` doctype (security review PART 3,
TASK 22).

``File`` is a Frappe core doctype used app-wide (avatars, print formats, every
doctype's attachments). Core already registers a permissive
``permission_query_conditions["File"]`` that, for a desk (System User) role,
admits any file whose ``attached_to_doctype`` is a doctype the caller can read.
The ``Jarvis User`` role grants read on ``Jarvis Conversation`` (the doctype),
so that clause admits EVERY user's inbound-doc File rows — leaking filenames,
``content_hash`` (an existence oracle), owner and the private ``file_url`` (the
bytes stay protected by core's per-doc ``File.has_permission`` deferral, but the
metadata leaks).

Frappe **ANDs** every registered ``permission_query_conditions`` hook for a
doctype, so this Jarvis fragment MUST be permissive for non-Jarvis files: it
only restricts rows attached to ``Jarvis Conversation`` and lets everything else
through. A conversation-attached File is visible when the caller owns the File
itself OR owns the linked conversation; all other files (``attached_to_doctype``
!= Jarvis Conversation, including NULL / other doctypes / public files) pass this
fragment unconditionally and are then subject only to core's own condition.

We register ONLY ``permission_query_conditions["File"]`` — deliberately NO
``has_permission["File"]`` hook: core's ``File.has_permission`` defers an
attached file's read to ``ref_doc.has_permission("read")`` (i.e. Part-1's
conversation gate), which already denies cross-user BYTE download; a second
Jarvis hook could only break that correct per-doc deferral.

Every interpolated value goes through ``frappe.db.escape``.
"""

from __future__ import annotations

import frappe

CONVERSATION = "Jarvis Conversation"


def _is_sm(user: str) -> bool:
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def file_query_conditions(user: str | None = None) -> str:
	"""Restrict ONLY Jarvis-Conversation-attached File rows to ones the caller
	owns (the File, or the linked conversation); every other File passes. Empty
	(no restriction) for System Manager / Administrator. Returned as a single
	parenthesized boolean expression that Frappe ANDs with core's File condition."""
	user = user or frappe.session.user
	if _is_sm(user):
		return ""
	esc = frappe.db.escape(user)
	return (
		"(ifnull(`tabFile`.`attached_to_doctype`, '') != 'Jarvis Conversation' "
		f"or `tabFile`.`owner` = {esc} "
		"or exists (select 1 from `tabJarvis Conversation` c "
		f"where c.name = `tabFile`.`attached_to_name` and c.owner = {esc}))"
	)
