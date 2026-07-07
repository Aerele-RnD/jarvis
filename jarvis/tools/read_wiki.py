"""jarvis__read_wiki: look up org wiki pages (Jarvis Wiki Page).

``slug`` returns ONE full page (body included); ``query`` searches Active
pages by slug/title/summary (LIKE) plus an exact ``ref_name`` match (so
"read the wiki on ACME Corp" finds ``customer--acme-corp`` by the record
name) and returns compact rows. Desk (System User) sessions only; reads go
through the normal doctype permissions (Desk User has read).
"""

import json

import frappe
from frappe.utils import cint

from jarvis.chat.wiki import is_stale
from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

WIKI = "Jarvis Wiki Page"
_MAX_LIMIT = 10


def _require_system_user() -> None:
	user = frappe.session.user
	if not user or user == "Guest":
		raise PermissionDeniedError("wiki tools require a signed-in desk user")
	if user == "Administrator":
		return
	if frappe.db.get_value("User", user, "user_type") != "System User":
		raise PermissionDeniedError("wiki tools require a desk (System User) session")


def read_wiki(query: str | None = None, slug: str | None = None, limit: int = 5):
	"""Read the org wiki: pass ``slug`` for one full page dict, or ``query``
	for a search returning ``[{slug, title, page_type, summary, stale}]``."""
	_require_system_user()
	if slug:
		return _get_by_slug(str(slug))
	if query:
		return _search(str(query), max(1, min(cint(limit) or 5, _MAX_LIMIT)))
	raise InvalidArgumentError("pass slug (one full page) or query (search)")


def _get_by_slug(slug: str) -> dict:
	slug = slug.strip().lower()
	name = frappe.db.get_value(WIKI, {"slug": slug}, "name")
	if not name:
		raise InvalidArgumentError(f"unknown wiki page: {slug}")
	if not frappe.has_permission(WIKI, ptype="read", doc=name):
		raise PermissionDeniedError(f"no read permission on {WIKI} {name}")
	doc = frappe.get_doc(WIKI, name)
	try:
		sources = json.loads(doc.sources) if doc.sources else []
	except Exception:
		sources = []
	return {
		"slug": doc.slug,
		"title": doc.title,
		"page_type": doc.page_type,
		"ref_doctype": doc.ref_doctype,
		"ref_name": doc.ref_name,
		"summary": doc.summary,
		"body_md": doc.body_md,
		"sensitivity": doc.sensitivity,
		"status": doc.status,
		"sources": sources if isinstance(sources, list) else [],
		"last_confirmed_at": str(doc.last_confirmed_at) if doc.last_confirmed_at else None,
		"contradiction_flag": cint(doc.contradiction_flag),
		"stale": is_stale(doc.last_confirmed_at, doc.modified),
	}


def _search(query: str, limit: int) -> list[dict]:
	query = query.strip()
	if not query:
		raise InvalidArgumentError("query must not be empty")
	if not frappe.has_permission(WIKI, ptype="read"):
		raise PermissionDeniedError(f"no read permission on {WIKI}")
	like = f"%{query[:140]}%"
	rows = frappe.get_all(
		WIKI,
		filters={"status": "Active"},
		or_filters=[
			["slug", "like", like],
			["title", "like", like],
			["summary", "like", like],
			["ref_name", "=", query],
		],
		fields=["slug", "title", "page_type", "summary", "last_confirmed_at", "modified"],
		order_by="modified desc",
		limit_page_length=limit,
	)
	return [
		{
			"slug": r.slug,
			"title": r.title,
			"page_type": r.page_type,
			"summary": r.summary,
			"stale": is_stale(r.get("last_confirmed_at"), r.get("modified")),
		}
		for r in rows
	]
