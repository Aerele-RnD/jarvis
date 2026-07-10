"""Real per-turn token-usage accounting for managed (gateway) chat.

The openclaw gateway's ``sessions.list`` rows carry per-session
``inputTokens`` / ``outputTokens`` that are **last-completed-run** numbers
(not cumulative), ``totalTokens`` (context size), and ``totalTokensFresh``
(validity marker). Accurate accounting therefore records a *delta at each
turn end* while the turn handler still holds the pooled gateway connection —
see ``jarvis.chat.turn_handler`` and the design at
``docs/superpowers/specs/2026-07-10-user-settings-usage-design.md``.

Three entry points:
  * ``get_or_create_user_settings(user)`` — race-safe lazy row creation with an
    explicit ``owner`` so the ``if_owner`` grant holds when an admin triggers it.
  * ``record_turn_usage(session_key, row)`` — atomic SQL increments on both the
    per-user ``Jarvis User Settings`` (month-rollover aware) and the cumulative
    ``Jarvis Chat Session`` fields. Never raises into the turn.
  * ``refresh_session_snapshots(rows)`` — the admin "sync from agent" sweep;
    refreshes per-session snapshot fields WITHOUT accumulating counters.
"""

from __future__ import annotations

import frappe

USER_SETTINGS = "Jarvis User Settings"
CHAT_SESSION = "Jarvis Chat Session"


def current_month_key() -> str:
	"""The current usage bucket as ``"YYYY-MM"`` (site timezone, matching the
	``now_datetime()`` stamps used for ``last_usage_at``)."""
	return frappe.utils.now_datetime().strftime("%Y-%m")


def get_or_create_user_settings(user: str):
	"""Return the ``Jarvis User Settings`` doc for ``user``, creating it if
	absent. Insert is ``ignore_permissions`` with an explicit ``owner=user`` so
	the ``if_owner`` permlevel-0 grant holds even when an admin (not the owner)
	triggered creation. Race-safe: a concurrent creator that wins the unique
	constraint just makes us re-read theirs."""
	existing = frappe.db.exists(USER_SETTINGS, {"user": user})
	if existing:
		return frappe.get_doc(USER_SETTINGS, existing)
	try:
		doc = frappe.get_doc({
			"doctype": USER_SETTINGS,
			"user": user,
			"owner": user,
		})
		doc.insert(ignore_permissions=True)
		# Frappe stamps ``owner`` from the session user at insert; force it back
		# to the settings owner so ``if_owner`` holds after an admin-triggered
		# create. update_modified=False keeps the audit stamp meaningful.
		if frappe.db.get_value(USER_SETTINGS, doc.name, "owner") != user:
			frappe.db.set_value(
				USER_SETTINGS, doc.name, "owner", user, update_modified=False
			)
		return frappe.get_doc(USER_SETTINGS, doc.name)
	except frappe.DuplicateEntryError:
		# A racing turn/request created the row between our exists() and insert;
		# the unique constraint on ``user`` (and the field:user autoname) is the
		# guard. Read the winner's row.
		return frappe.get_doc(USER_SETTINGS, {"user": user})


def record_turn_usage(session_key: str, row: dict | None) -> None:
	"""Record one completed turn's token delta from a ``sessions.list`` row.

	``row`` is the gateway row for THIS session (matched by ``key`` upstream).
	``inputTokens``/``outputTokens`` are last-run values, so the turn delta is
	their sum; ``totalTokens`` is the context size (snapshot only). A row with
	``totalTokensFresh`` false/missing, or null token fields, is do-not-record.

	Increments (atomic SQL, not doc.save):
	  * ``Jarvis User Settings``: month_* += delta with month rollover (a stale
	    ``usage_month`` resets the month buckets to this delta), total_tokens
	    += delta, usage_month/last_usage_at refreshed.
	  * ``Jarvis Chat Session``: input_tokens/output_tokens += the run values,
	    run_count += 1, last_total_tokens/last_usage_at snapshotted.

	Resolves the user via ``Jarvis Chat Session``; silently no-ops when no
	mapping exists. NEVER raises — a usage-accounting bug must not break chat."""
	try:
		if not row or not row.get("totalTokensFresh"):
			return
		raw_in = row.get("inputTokens")
		raw_out = row.get("outputTokens")
		if raw_in is None and raw_out is None:
			return
		input_tokens = int(raw_in or 0)
		output_tokens = int(raw_out or 0)
		delta = input_tokens + output_tokens
		if delta <= 0:
			return
		context_tokens = int(row.get("totalTokens") or 0)

		user = frappe.db.get_value(CHAT_SESSION, {"session_key": session_key}, "user")
		if not user:
			return

		# Ensure the per-user row exists (in this same transaction) before the
		# atomic UPDATE targets it.
		get_or_create_user_settings(user)

		now = frappe.utils.now_datetime()
		month = current_month_key()
		params = {
			"in": input_tokens,
			"out": output_tokens,
			"delta": delta,
			"ctx": context_tokens,
			"month": month,
			"now": now,
			"user": user,
			"session_key": session_key,
		}
		# Month rollover done inside SQL so the read-modify-write is atomic:
		# when usage_month already matches, add; otherwise reset the month
		# buckets to this delta. total_tokens is all-time and never resets.
		frappe.db.sql(
			"""
			UPDATE `tabJarvis User Settings`
			SET
				month_input_tokens = CASE WHEN usage_month = %(month)s
					THEN month_input_tokens + %(in)s ELSE %(in)s END,
				month_output_tokens = CASE WHEN usage_month = %(month)s
					THEN month_output_tokens + %(out)s ELSE %(out)s END,
				month_tokens = CASE WHEN usage_month = %(month)s
					THEN month_tokens + %(delta)s ELSE %(delta)s END,
				total_tokens = total_tokens + %(delta)s,
				usage_month = %(month)s,
				last_usage_at = %(now)s,
				modified = %(now)s
			WHERE user = %(user)s
			""",
			params,
		)
		frappe.db.sql(
			"""
			UPDATE `tabJarvis Chat Session`
			SET
				input_tokens = input_tokens + %(in)s,
				output_tokens = output_tokens + %(out)s,
				run_count = run_count + 1,
				last_total_tokens = %(ctx)s,
				last_usage_at = %(now)s
			WHERE session_key = %(session_key)s
			""",
			params,
		)
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			title="jarvis usage: record_turn_usage failed",
			message=frappe.get_traceback(),
		)


def refresh_session_snapshots(rows: list[dict]) -> dict:
	"""Refresh per-session snapshot fields from a ``sessions.list`` sweep,
	WITHOUT accumulating counters (the "sync from agent" endpoint).

	For every gateway row that maps to a known ``Jarvis Chat Session``, snapshot
	``last_total_tokens`` (= context size) and ``last_usage_at``; stamp the
	owning user's ``Jarvis User Settings.last_synced_at``. Returns a per-user
	summary ``{user: {sessions, last_total_tokens}}`` for the admin UI. Best
	effort per row; a malformed row is skipped, never raised."""
	summary: dict[str, dict] = {}
	now = frappe.utils.now_datetime()
	touched_users: set[str] = set()
	for row in rows or []:
		try:
			if not isinstance(row, dict):
				continue
			session_key = row.get("key")
			if not session_key:
				continue
			user = frappe.db.get_value(
				CHAT_SESSION, {"session_key": session_key}, "user"
			)
			if not user:
				continue
			context_tokens = int(row.get("totalTokens") or 0)
			frappe.db.sql(
				"""
				UPDATE `tabJarvis Chat Session`
				SET last_total_tokens = %(ctx)s, last_usage_at = %(now)s
				WHERE session_key = %(session_key)s
				""",
				{"ctx": context_tokens, "now": now, "session_key": session_key},
			)
			touched_users.add(user)
			bucket = summary.setdefault(
				user, {"sessions": 0, "last_total_tokens": 0}
			)
			bucket["sessions"] += 1
			bucket["last_total_tokens"] += context_tokens
		except Exception:
			frappe.log_error(
				title="jarvis usage: snapshot refresh row failed",
				message=frappe.get_traceback(),
			)
	for user in touched_users:
		try:
			get_or_create_user_settings(user)
			frappe.db.set_value(
				USER_SETTINGS, {"user": user}, "last_synced_at", now,
				update_modified=False,
			)
		except Exception:
			frappe.log_error(
				title="jarvis usage: last_synced_at stamp failed",
				message=frappe.get_traceback(),
			)
	frappe.db.commit()
	return summary
