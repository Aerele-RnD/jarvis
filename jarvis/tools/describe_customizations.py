"""Live, permission-fenced index of THIS site's customizations.

Pipeline: collect_profile() -> fence_for_user(session user) ->
apply_scope_match -> render_profile_md. NO caching in v1 - the collector is a
handful of aggregates over small metadata tables (milliseconds). If profiling
ever demands one: cache the RAW collect output per-site and fence per-user
AFTER the cache read; NEVER cache fenced or rendered output site-wide - that
would hand every user the widest view (the role-blind leak this tool's design
exists to avoid).
"""

from __future__ import annotations

import frappe  # noqa: F401 - session user default rides frappe via fence

from jarvis.exceptions import InvalidArgumentError
from jarvis.site_profile.collect import collect_profile
from jarvis.site_profile.fence import fence_for_user
from jarvis.site_profile.render import EMPTY_MESSAGE, apply_scope_match, render_profile_md

_SCOPES = frozenset({
	"apps", "doctypes", "custom_fields", "workflows", "reports",
	"print_formats", "scripts",
})

_SCOPED_EMPTY = (
	"No customizations match the requested scope/filter. "
	"Call without scope/match for the full index."
)


def describe_customizations(scope=None, match=None) -> dict:
	"""Live index of THIS site's customizations: custom apps, custom DocTypes,
	custom fields on core doctypes, workflows, reports. Call once per
	conversation when a request names an entity not covered by the standard
	skills, or when the [Context:] line mentions custom apps. Then call
	``get_schema`` for field-level detail.

	- ``scope``: optional subset of {apps, doctypes, custom_fields, workflows,
	  reports, print_formats, scripts} - list or comma-separated string.
	  Default = the full index.
	- ``match``: optional case-insensitive substring over customization names.

	Result: {markdown} - an INDEX, not a schema dump: names, counts and
	workflow states only, budget-capped, ending with the retrieval recipe.
	Permission-fenced per calling user: doctypes the caller cannot read are
	absent and never counted, so two users may legitimately see different
	indexes. Metadata only - no row data, Select options, or field
	descriptions ever appear.
	"""
	scopes = _parse_scope(scope)
	needle = _parse_match(match)
	data = fence_for_user(collect_profile())
	filtered = apply_scope_match(data, scopes, needle)
	empty_message = _SCOPED_EMPTY if (scopes or needle) else EMPTY_MESSAGE
	return {"markdown": render_profile_md(filtered, empty_message=empty_message)}


def _parse_scope(scope) -> set[str] | None:
	if scope is None or scope == "" or scope == []:
		return None
	if isinstance(scope, str):
		parts = [p.strip().lower() for p in scope.split(",") if p.strip()]
	elif isinstance(scope, (list, tuple)):
		parts = [str(p).strip().lower() for p in scope if str(p).strip()]
	else:
		raise InvalidArgumentError("scope must be a list or comma-separated string")
	if not parts:
		return None
	unknown = sorted(set(parts) - _SCOPES)
	if unknown:
		raise InvalidArgumentError(
			f"unknown scope value(s): {', '.join(unknown)}; "
			f"allowed: {', '.join(sorted(_SCOPES))}"
		)
	return set(parts)


def _parse_match(match) -> str | None:
	if match is None:
		return None
	if not isinstance(match, str):
		raise InvalidArgumentError("match must be a string")
	return match.strip().lower() or None
