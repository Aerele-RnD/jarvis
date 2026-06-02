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

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

MAX_LIMIT = 1000
DEFAULT_LIMIT = 100

# Identifiers we refuse outright in any token stream - covers single-line
# comments (--), block comments (/* */), and forbidden statement types that
# might slip past sqlparse's get_type() in edge cases (subqueries, CTEs).
_FORBIDDEN_TOKENS = {
	"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE",
	"RENAME", "GRANT", "REVOKE", "REPLACE", "CALL", "EXEC", "EXECUTE",
	"LOAD", "HANDLER", "LOCK", "UNLOCK", "USE", "SET",
}

# Match `tab<DocType>` after FROM/JOIN. We accept backticks too:
# `FROM \`tabSales Invoice\` AS si JOIN tabSales Invoice Item AS sii ...`
_TABLE_RE = re.compile(
	r"\b(?:FROM|JOIN)\s+(?:`(tab[^`]+)`|(tab[A-Za-z0-9_ ]+))",
	re.IGNORECASE,
)


def run_query(query: str, limit: int = DEFAULT_LIMIT) -> dict:
	"""Execute a validated read-only SELECT and return rows + the executed SQL.

	Returns ``{"sql": <final query with limit>, "rows": [...]}``. The
	executed SQL is included so the model can show the user what ran and so
	debugging is straightforward.
	"""
	if not query or not query.strip():
		raise InvalidArgumentError("query is required")
	if limit <= 0 or limit > MAX_LIMIT:
		raise InvalidArgumentError(f"limit must be between 1 and {MAX_LIMIT}")

	clean = query.strip().rstrip(";").strip()
	_reject_comments(clean)
	_reject_multi_statement(clean)
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

	final = _enforce_limit(clean, limit)

	rows = frappe.db.sql(final, as_dict=True)
	# frappe.db.sql can return tuples in some edge cases; force list-of-dicts
	if rows and not isinstance(rows[0], dict):
		raise InvalidArgumentError(
			"query did not return named columns; add explicit column aliases"
		)
	return {"sql": final, "rows": rows}


# ---- Validation helpers ----------------------------------------------


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
	# Any non-tab table reference is a smell: refuse rather than silently
	# allow access to non-DocType tables (`__Auth`, internal tables, etc.).
	for m in re.finditer(r"\b(?:FROM|JOIN)\s+(`?\w[^\s`,()]*`?)", query, re.IGNORECASE):
		raw = m.group(1).strip("`").strip()
		# Frappe table names always start with `tab` or are derived (`tabDocType`).
		# Anything else means the query is touching a non-public table.
		if raw and not raw.startswith("tab"):
			raise InvalidArgumentError(
				f"only `tab<DocType>` tables are allowed; got: {raw}"
			)
	return seen


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
