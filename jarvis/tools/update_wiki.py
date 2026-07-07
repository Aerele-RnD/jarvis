"""jarvis__update_wiki: create or update one org wiki page (Jarvis Wiki Page).

Prefer ``append_md`` (adds a section, keeps everything already recorded) over
``replace_body_md`` (full rewrite); passing both is rejected so an intent is
never half-applied. Creating a NEW page additionally requires ``title`` and
``page_type``; the slug grammar is enforced by the doctype controller. Desk
(System User) sessions only; the write itself goes through normal doctype
permissions (Desk User has write/create). Registered as a gated write in
jarvis.api (_WRITE_TOOLS + _GATED_WRITES, never auto-applied).
"""

import frappe

from jarvis.chat.wiki import PAGE_TYPES, append_source
from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

WIKI = "Jarvis Wiki Page"


def _require_system_user() -> None:
	user = frappe.session.user
	if not user or user == "Guest":
		raise PermissionDeniedError("wiki tools require a signed-in desk user")
	if user == "Administrator":
		return
	if frappe.db.get_value("User", user, "user_type") != "System User":
		raise PermissionDeniedError("wiki tools require a desk (System User) session")


def update_wiki(
	slug: str,
	title: str | None = None,
	page_type: str | None = None,
	ref_doctype: str | None = None,
	ref_name: str | None = None,
	summary: str | None = None,
	append_md: str | None = None,
	replace_body_md: str | None = None,
) -> dict:
	"""Create or update the wiki page ``slug``. ``append_md`` appends a
	section to the existing body (preferred); ``replace_body_md`` rewrites it.
	Returns a compact summary of the saved page."""
	_require_system_user()

	slug = (slug or "").strip().lower()
	if not slug:
		raise InvalidArgumentError("slug is required")
	if append_md and replace_body_md:
		raise InvalidArgumentError(
			"pass either append_md or replace_body_md, not both"
		)
	if page_type and page_type not in PAGE_TYPES:
		raise InvalidArgumentError(
			f"page_type must be one of: {', '.join(PAGE_TYPES)}"
		)

	name = frappe.db.get_value(WIKI, {"slug": slug}, "name")
	if name:
		doc = frappe.get_doc(WIKI, name)
		if not frappe.has_permission(WIKI, ptype="write", doc=doc):
			raise PermissionDeniedError(f"no write permission on {WIKI} {name}")
		created = False
		if title and str(title).strip():
			doc.title = str(title).strip()[:140]
		if page_type:
			doc.page_type = page_type
		if ref_doctype is not None and str(ref_doctype).strip():
			doc.ref_doctype = str(ref_doctype).strip()
		if ref_name is not None and str(ref_name).strip():
			doc.ref_name = str(ref_name).strip()
		if summary is not None:
			doc.summary = " ".join(str(summary).split()) or None
		if append_md and str(append_md).strip():
			existing = (doc.body_md or "").strip()
			doc.body_md = f"{existing}\n\n{str(append_md).strip()}".strip()
		elif replace_body_md is not None:
			doc.body_md = str(replace_body_md)
		append_source(doc, "tool", None, frappe.session.user)
		doc.last_confirmed_at = frappe.utils.now_datetime()
		doc.save()
	else:
		if not (title and str(title).strip()) or not page_type:
			raise InvalidArgumentError(
				"creating a new wiki page requires title and page_type"
			)
		created = True
		doc = frappe.get_doc({
			"doctype": WIKI,
			"slug": slug,
			"title": str(title).strip()[:140],
			"page_type": page_type,
			"ref_doctype": (str(ref_doctype).strip() if ref_doctype else None),
			"ref_name": (str(ref_name).strip() if ref_name else None),
			"summary": (" ".join(str(summary).split()) or None) if summary is not None else None,
			"body_md": str(replace_body_md or append_md or "").strip(),
			"status": "Active",
			"last_confirmed_at": frappe.utils.now_datetime(),
		})
		append_source(doc, "tool", None, frappe.session.user)
		doc.insert()

	return {
		"ok": True,
		"created": created,
		"slug": doc.slug,
		"title": doc.title,
		"page_type": doc.page_type,
		"status": doc.status,
		"body_chars": len(doc.body_md or ""),
	}
