"""Per-tool implementations live in sibling modules
(jarvis.tools.get_doc, etc.); they're dispatched by
jarvis.tools.registry.

Shared helpers go here so per-tool files don't repeat them.
"""

from __future__ import annotations

from jarvis.exceptions import InvalidArgumentError


def require_doctype_and_name(doctype: str, name: str) -> None:
	"""Reject empty doctype / name with InvalidArgumentError.

	Six tools (amend_doc, cancel_doc, delete_doc, get_doc, submit_doc,
	update_doc) all start with the identical two-line guard; the
	2026-06-16 review flagged this as duplicated prologue. Factored
	here so future tools that take a (doctype, name) pair have one
	place to import from and changes to the rejection message land
	in one site.
	"""
	if not doctype:
		raise InvalidArgumentError("doctype is required")
	if not name:
		raise InvalidArgumentError("name is required")
