"""Read-only SQL select against Frappe DocType tables.

For complex requests the LLM struggles to express through ``get_list`` -
joins, aggregations, group-by, cross-DocType analytics - this tool lets the
agent compose a SELECT and execute it. Safety is enforced through query
parsing, not just trust:

- Only one statement per call.
- Only SELECT (no DML/DDL keywords; no comments; no multi-statement).
- Every FROM/JOIN target must be a Frappe DocType table (``tab<DocType>``).
- The calling user must have DocType-level read permission on every
  referenced DocType.
- A row cap is enforced; the tool injects ``LIMIT`` if missing.

**Caveat:** DocType-level perms only. User Permissions and record-level
share/role filters are NOT enforced (Frappe's permission engine doesn't
have a public hook for arbitrary SQL). Document this in the tool
description so the model picks ``get_list`` for record-scoped queries.
"""

from __future__ import annotations

import re

import frappe
import sqlparse
from sqlparse.sql import Identifier, IdentifierList
from sqlparse.tokens import DDL, DML, Keyword

from jarvis.exceptions import (
	InvalidArgumentError,
	PermissionDeniedError,
	ResultTooLargeError,
)

MAX_LIMIT = 1000
DEFAULT_LIMIT = 100

# Row guard: refuse a result over this size unless the caller passes
# ``confirm_large=True``. Sits below ``MAX_LIMIT`` (the hard ceiling on
# the SQL ``LIMIT`` clause) and above the default ``DEFAULT_LIMIT`` so
# that ordinary queries with no explicit limit fit silently and only
# the agent's wide ``limit=N`` calls trigger the guard. See the
# ``ResultTooLargeError`` docstring for the load-bearing rationale (the
# 2026-06-22 outage on openai/gpt-5.5).
ROW_GUARD = 200

# Identifiers we refuse outright in any token stream - covers single-line
# comments (--), block comments (/* */), and forbidden statement types that
# might slip past sqlparse's get_type() in edge cases (subqueries, CTEs).
#
# Sprint-1 (2026-06-16 review) extra entries: keywords that compose into
# real attacks even from inside a SELECT:
#   - INTO         dangerous in "SELECT ... INTO OUTFILE 'p'" (filesystem write)
#   - OUTFILE      same
#   - DUMPFILE     same
#   - LOAD_FILE    function form of filesystem read
#   - SLEEP        DoS via tied-up connections, also a timing oracle
#   - BENCHMARK    same family
#   - GET_LOCK     hold a named lock indefinitely -> DoS
#   - RELEASE_LOCK release someone else's lock -> coordination DoS
#   - IS_FREE_LOCK / IS_USED_LOCK probe for lock holders
_FORBIDDEN_TOKENS = {
	"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
	"RENAME", "GRANT", "REVOKE", "REPLACE", "CALL", "EXEC", "EXECUTE",
	"LOAD", "HANDLER", "LOCK", "UNLOCK", "USE", "SET",
	"INTO", "OUTFILE", "DUMPFILE",
}

# Function-shaped attacks. sqlparse classifies these as Name (function call)
# rather than Keyword, so the token-stream check above won't catch them.
# We re-check via a case-insensitive substring search on the cleaned query.
# Each entry is matched as a word boundary; ``LOAD_FILE`` alone would not
# false-positive a column named ``upload_filename``.
_FORBIDDEN_FUNCTIONS = (
	"LOAD_FILE", "SLEEP", "BENCHMARK",
	"GET_LOCK", "RELEASE_LOCK", "RELEASE_ALL_LOCKS",
	"IS_FREE_LOCK", "IS_USED_LOCK",
)

# Schemas that have no business being touched from an agent-driven SELECT.
# Catching these specifically defends against the ``FROM tabUser,
# information_schema.tables t`` comma-FROM trick the table extractor's
# leading-FROM regex misses.
_FORBIDDEN_SCHEMAS = ("information_schema", "mysql", "performance_schema", "sys")

# Match `tab<DocType>` after FROM/JOIN. We accept backticks too:
# `FROM \`tabSales Invoice\` AS si JOIN tabSales Invoice Item AS sii ...`
_TABLE_RE = re.compile(
	r"\b(?:FROM|JOIN)\s+(?:`(tab[^`]+)`|(tab[A-Za-z0-9_ ]+))",
	re.IGNORECASE,
)


def run_query(
	query: str,
	limit: int = DEFAULT_LIMIT,
	confirm_large: bool = False,
) -> dict:
	"""Execute a validated read-only SELECT and return rows + the executed SQL.

	Returns ``{"sql": <final query with limit>, "rows": [...]}``. The
	executed SQL is included so the model can show the user what ran and so
	debugging is straightforward.

	Row guard: results above ``ROW_GUARD`` (200) rows raise
	``ResultTooLargeError`` unless ``confirm_large=True``. The agent should
	respond to that error by narrowing the filter, aggregating the query
	(``GROUP BY``/``COUNT``/``SUM``), or - when a row dump genuinely IS the
	answer (export, audit) - retrying with ``confirm_large=True``. See the
	``ResultTooLargeError`` docstring for the 2026-06-22 outage that
	motivated this guard.
	"""
	if not query or not query.strip():
		raise InvalidArgumentError("query is required")
	if limit <= 0 or limit > MAX_LIMIT:
		raise InvalidArgumentError(f"limit must be between 1 and {MAX_LIMIT}")

	clean = query.strip().rstrip(";").strip()
	_reject_comments(clean)
	_reject_multi_statement(clean)
	_reject_forbidden_functions(clean)
	_reject_forbidden_schemas(clean)
	parsed = _parse_single_select(clean)
	_reject_forbidden_keywords(parsed)
	tables = _extract_tables(clean)
	if not tables:
		raise InvalidArgumentError(
			"query references no Frappe DocType table (`tab<DocType>` form required)"
		)
	for tbl in tables:
		doctype = tbl[len("tab"):]
		if not frappe.has_permission(doctype, ptype="read"):
			raise PermissionDeniedError(
				f"no read permission on referenced DocType: {doctype}"
			)

	# Operator-configured defense-in-depth: a per-site DocType allowlist on
	# top of the Frappe permission system. If set, run_query refuses any
	# DocType not on the list - even when the calling user has read perm.
	# Closes Sprint-1 punch-list "run_query SQL allowlist has bypass
	# surfaces" by giving operators a way to lock the tool to a known-good
	# slice of the DocType graph (e.g. "Sales Invoice, Customer, Item")
	# so a future allowlist bypass in the SQL parser is contained.
	allowlist = _load_doctype_allowlist()
	if allowlist is not None:
		for tbl in tables:
			doctype = tbl[len("tab"):]
			if doctype not in allowlist:
				raise PermissionDeniedError(
					f"DocType {doctype!r} is not in this site's run_query "
					f"allowlist; add it to Jarvis Settings."
					f"run_query_doctype_allowlist to enable."
				)

	final = _enforce_limit(clean, limit)

	rows = frappe.db.sql(final, as_dict=True)
	# frappe.db.sql can return tuples in some edge cases; force list-of-dicts
	if rows and not isinstance(rows[0], dict):
		raise InvalidArgumentError(
			"query did not return named columns; add explicit column aliases"
		)
	if len(rows) > ROW_GUARD and not confirm_large:
		raise ResultTooLargeError(
			row_count=len(rows),
			limit=ROW_GUARD,
			tool="run_query",
		)
	return {"sql": final, "rows": rows}


# ---- Validation helpers ----------------------------------------------


def _load_doctype_allowlist() -> set[str] | None:
	"""Read the per-site DocType allowlist from Jarvis Settings.

	Returns ``None`` when the field is unset or empty (default; means
	"no extra restriction beyond Frappe permissions"). Returns a
	normalised set of DocType names when configured. Accepts comma OR
	newline separation so operators can paste from either a CSV row or
	a one-DocType-per-line list, the latter being the more readable
	form for >5 entries in the Small Text field.

	Whitespace is trimmed; empty entries are dropped. Names are NOT
	normalised for case (Frappe DocType names are case-sensitive:
	"Sales Invoice" != "sales invoice"), so a typo in the allowlist
	silently doesn't match - that's the right failure mode (closed by
	default).

	Reads via ``frappe.get_cached_doc`` rather than ``get_single_value``
	so the call uses Frappe's Single-doc cache (a single in-memory dict
	per process) instead of an SQL round-trip. The cached path also
	doesn't get fooled by callers who have ``patch('frappe.db.sql')``
	in scope (a common pattern in run_query's own tests).
	"""
	try:
		settings = frappe.get_cached_doc("Jarvis Settings")
	except Exception:
		# Bench misconfig / migration in flight / similar. Failing open
		# here is the safe call: the actual perm check above already
		# gated every DocType through frappe.has_permission. Without
		# this fallback, a transient Settings read error would brick
		# every run_query call.
		return None
	raw = (settings.get("run_query_doctype_allowlist") or "").strip()
	if not raw:
		return None
	parts = re.split(r"[,\n]", raw)
	cleaned = {p.strip() for p in parts if p.strip()}
	return cleaned if cleaned else None


def _reject_comments(query: str) -> None:
	"""Reject SQL comments. They're a common injection vector (smuggling a
	second statement after a `--`) and have no legitimate use from an LLM."""
	if "--" in query or "/*" in query or "*/" in query or "#" in query:
		raise InvalidArgumentError("SQL comments are not allowed")


def _reject_multi_statement(query: str) -> None:
	"""Reject embedded semicolons. We've already stripped a single trailing
	semicolon; anything left means a second statement is hiding."""
	if ";" in query:
		raise InvalidArgumentError("multiple statements are not allowed")


def _reject_forbidden_functions(query: str) -> None:
	"""Refuse MySQL function calls that compose into DoS / FS-read attacks
	even from inside a SELECT. sqlparse tokenizes ``LOAD_FILE(`` as a Name
	(function call) rather than a Keyword, so the token-stream
	walker won't catch it.

	Word-boundary regex so a benign column like ``upload_filename`` is not
	false-matched against ``LOAD_FILE``.
	"""
	for fn in _FORBIDDEN_FUNCTIONS:
		if re.search(rf"\b{re.escape(fn)}\s*\(", query, re.IGNORECASE):
			raise InvalidArgumentError(
				f"function not allowed: {fn} (DoS or filesystem-access surface)"
			)


def _reject_forbidden_schemas(query: str) -> None:
	"""Catch the comma-FROM cross-schema trick:
	``FROM tabUser, information_schema.tables t``. The leading-FROM table
	extractor below only checks the first table after FROM/JOIN, so a
	second comma-separated table referencing ``information_schema`` would
	slip past the ``tab<DocType>`` requirement.

	Schema-qualified identifiers in MySQL use ``schema.table``; an explicit
	textual reject of the dangerous schemas closes the comma-FROM hole
	regardless of how the LLM phrases it.
	"""
	for schema in _FORBIDDEN_SCHEMAS:
		# Match ``information_schema.`` (case-insensitive, word-anchored
		# before the dot). Also catch backtick-quoted form.
		if re.search(rf"\b{re.escape(schema)}\s*\.", query, re.IGNORECASE):
			raise InvalidArgumentError(
				f"queries against schema {schema!r} are not allowed"
			)
		if re.search(rf"`{re.escape(schema)}`\s*\.", query, re.IGNORECASE):
			raise InvalidArgumentError(
				f"queries against schema {schema!r} are not allowed"
			)


def _parse_single_select(query: str):
	"""Return the single sqlparse Statement object, ensuring it's a SELECT."""
	statements = sqlparse.parse(query)
	if len(statements) != 1:
		raise InvalidArgumentError("query must contain exactly one statement")
	stmt = statements[0]
	if (stmt.get_type() or "").upper() != "SELECT":
		raise InvalidArgumentError("only SELECT statements are allowed")
	return stmt


def _reject_forbidden_keywords(stmt) -> None:
	"""Walk the token stream and refuse known dangerous keywords. sqlparse's
	``get_type()`` only inspects the leading keyword - a SELECT containing a
	subquery DELETE would slip past."""
	for token in stmt.flatten():
		if token.ttype in (DDL, DML):
			val = token.value.upper()
			if val in _FORBIDDEN_TOKENS:
				raise InvalidArgumentError(f"keyword not allowed: {val}")
		elif token.ttype is Keyword:
			val = token.value.upper()
			if val in _FORBIDDEN_TOKENS:
				raise InvalidArgumentError(f"keyword not allowed: {val}")


def _extract_tables(query: str) -> list[str]:
	"""Return distinct `tabXxx` references from FROM/JOIN clauses.

	Uses a regex because sqlparse's table-extraction helpers handle the
	common cases but lose Frappe's space-containing table names like
	``tabSales Invoice Item``. The regex is permissive on what it matches
	and the caller verifies the corresponding DocType exists via
	``frappe.has_permission``.
	"""
	seen = []
	for m in _TABLE_RE.finditer(query):
		raw = (m.group(1) or m.group(2) or "").strip()
		if raw and raw not in seen:
			seen.append(raw)
	# Walk every FROM/JOIN clause and tokenize comma-separated table lists.
	# Defends against ``FROM tabUser, tabHidden`` (second table silently
	# missing from the perm check) and ``FROM tabUser, secret_table t``
	# (second table not a tab*). The leading-FROM regex above only checked
	# the FIRST identifier after each FROM/JOIN.
	for raw in _comma_from_table_list(query):
		if not raw.startswith("tab"):
			raise InvalidArgumentError(
				f"only `tab<DocType>` tables are allowed; got: {raw}"
			)
		# Comma-separated tab tables are legal, but the leading-FROM
		# extractor missed them; fold them in so the permission check
		# below covers EVERY referenced DocType.
		if raw not in seen:
			seen.append(raw)
	return seen


# Words that terminate a FROM/JOIN table list in standard SQL. Lowercased
# for case-insensitive matching after we lowercase the input.
_FROM_TERMINATORS = (
	"where", "group", "order", "limit", "having", "join", "on", "union",
	"into", "for",
)


def _comma_from_table_list(query: str) -> list[str]:
	"""Tokenize every FROM/JOIN clause's comma-separated table list.

	For ``FROM tabUser u, information_schema.tables t WHERE ...`` returns
	``["tabUser", "information_schema.tables"]``. Aliases stripped.

	Returns lower-cased-input-derived raw identifiers; callers compare to
	``tab`` (lowercase). Backticks stripped.
	"""
	out: list[str] = []
	lowered = query.lower()
	# Find every FROM/JOIN start.
	for m in re.finditer(r"\b(?:from|join)\s+", lowered):
		start = m.end()
		# End of the clause = next terminator keyword OR end of string.
		end = len(lowered)
		for term in _FROM_TERMINATORS:
			t_m = re.search(rf"\b{term}\b", lowered[start:])
			if t_m:
				end = min(end, start + t_m.start())
		clause_lower = lowered[start:end]
		clause_orig = query[start:end]
		# Strip parenthesized subexpressions so a subquery's comma doesn't
		# split the outer list. Naive paren-skip is fine here because we
		# only care about table identifiers, not the subquery's contents.
		clause_orig = re.sub(r"\([^()]*\)", "", clause_orig)
		for piece in clause_orig.split(","):
			ident = piece.strip().split()[0] if piece.strip() else ""
			ident = ident.strip("`").strip()
			if not ident:
				continue
			# Lowercase only the schema-prefix comparison; preserve the
			# table-name case for the perm check downstream (Frappe
			# DocTypes are mixed case: "Sales Invoice").
			out.append(ident)
	return out


def _enforce_limit(query: str, limit: int) -> str:
	"""Ensure the query ends with a LIMIT no larger than the cap."""
	# Detect an existing LIMIT and clamp it; otherwise append.
	m = re.search(r"\bLIMIT\s+(\d+)(?:\s*,\s*(\d+))?\s*$", query, re.IGNORECASE)
	if m:
		# `LIMIT n` or `LIMIT offset, n`
		if m.group(2) is not None:
			offset, n = int(m.group(1)), int(m.group(2))
			n = min(n, limit)
			return re.sub(
				r"\bLIMIT\s+\d+\s*,\s*\d+\s*$",
				f"LIMIT {offset}, {n}",
				query,
				flags=re.IGNORECASE,
			)
		n = min(int(m.group(1)), limit)
		return re.sub(r"\bLIMIT\s+\d+\s*$", f"LIMIT {n}", query, flags=re.IGNORECASE)
	return f"{query} LIMIT {limit}"


# sqlparse imports above are intentionally module-level so we fail fast on
# missing dep at import time (Frappe ships with sqlparse, so this should
# always be present - but the import is the contract).
_ = IdentifierList, Identifier  # silence "unused import" when reading
