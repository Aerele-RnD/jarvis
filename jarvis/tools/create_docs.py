"""Create several documents in one confirmed, atomic batch.

Sibling of create_doc for the case where a create needs its dependencies made
first (a new Customer + a new Item before the Sales Invoice that links them).
The agent gathers the missing masters (resolve_links + get_creation_context) and
submits them here as ONE list, so the user confirms the whole set with a single
gated card instead of one per record. All inserts run in one transaction guarded
by a savepoint: if any fails, the whole batch rolls back (the caller catches the
error and would otherwise commit the partial inserts). Order matters — put a
dependency before the doc that links it.
"""

from collections import deque

import frappe

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools.create_doc import _set_title_from_title_field, _validate_create_args

_MAX_BATCH = 20


def create_docs(docs: list, notes: list | None = None) -> dict:
	"""Insert every ``{"doctype", "values"}`` in ``docs`` atomically.

	Returns ``{"created": [{"doctype", "name"}, ...], "notes": [...]}`` — a lean
	shape (no full doc dump, so no permlevel>0 field leaks). ``notes`` are
	display-only lines echoed back for the confirmation card.
	"""
	if not isinstance(docs, list) or not docs:
		raise InvalidArgumentError(
			"docs must be a non-empty list of {doctype, values}"
		)
	if len(docs) > _MAX_BATCH:
		raise InvalidArgumentError(f"too many docs in one batch (max {_MAX_BATCH})")
	for i, item in enumerate(docs):
		if not isinstance(item, dict):
			raise InvalidArgumentError(f"docs[{i}] must be a dict with doctype + values")
		values = item.get("values")
		# Reuse create_doc's guards: non-empty values, no protected fields,
		# per-doctype create permission. Raises InvalidArgumentError /
		# PermissionDeniedError exactly as a single create would.
		_validate_create_args(item.get("doctype"), values if isinstance(values, dict) else {})

	created = []
	sp = "jcd_" + frappe.generate_hash(length=10)
	# frappe.db.rollback(save_point=...) only issues ROLLBACK TO SAVEPOINT — it
	# does not clear the before/after-commit or after-rollback callback queues.
	# So on failure, callbacks queued by the docs that got inserted-then-rolled-
	# back would otherwise survive and fire on the request's real commit. Snapshot
	# here and restore only on failure; on success the queues are left alone so
	# the (real, kept) docs' callbacks fire normally.
	saved_queues = {
		name: tuple(getattr(frappe.db, name)._functions)
		for name in ("before_commit", "after_commit", "after_rollback")
		if hasattr(frappe.db, name)
	}
	frappe.db.savepoint(sp)
	try:
		for item in docs:
			doc = frappe.new_doc(item["doctype"])
			for field, value in item["values"].items():
				doc.set(field, value)
			_set_title_from_title_field(doc)
			doc.insert()  # links to earlier docs in this batch resolve (same txn)
			created.append({"doctype": doc.doctype, "name": doc.name})
	except Exception:
		# The caller (_dispatch_and_wrap / dispatch_confirmed) catches and would
		# commit at request end, so undo the partial batch here.
		frappe.db.rollback(save_point=sp)
		for name, functions in saved_queues.items():
			getattr(frappe.db, name)._functions = deque(functions)
		raise
	return {"created": created, "notes": list(notes) if isinstance(notes, list) else []}
