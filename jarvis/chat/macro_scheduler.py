"""Scheduled macro runs.

An hourly cron (``jarvis.hooks.scheduler_events``) calls :func:`run_due_macros`,
which fires every enabled macro whose ``next_run_at`` has passed — running it as
the macro's owner (so the result conversation is theirs) and advancing
``next_run_at`` for the next occurrence. Modeled on
``jarvis.chat.stale_scan.scan_and_mark_errored``.
"""

import datetime

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

MACRO = "Jarvis Macro"

_DEFAULT_SECONDS = 9 * 3600  # 09:00 when no schedule_time set


def run_due_macros() -> None:
	"""Run every enabled macro whose next_run_at is due. Runs as Administrator
	(the scheduler user); each macro executes as its own owner."""
	now = now_datetime()
	due = frappe.get_all(
		MACRO,
		filters={"schedule_enabled": 1, "next_run_at": ["<=", now]},
		fields=["name", "owner", "schedule_frequency", "schedule_time"],
	)
	if not due:
		return

	original_user = frappe.session.user
	for m in due:
		try:
			frappe.set_user(m.owner)
			from jarvis.chat import macros

			macros.run_macro(m.name, trigger="scheduled")
		except Exception:
			frappe.log_error(
				title=f"jarvis scheduled macro failed: {m.name}",
				message=frappe.get_traceback(),
			)
		finally:
			frappe.set_user(original_user)
		# Advance the schedule with a raw set_value (no re-validate, which would
		# otherwise recompute next_run_at itself).
		frappe.db.set_value(
			MACRO,
			m.name,
			{
				"last_run_at": now,
				"next_run_at": compute_next_run(m.schedule_frequency, m.schedule_time, from_dt=now),
			},
			update_modified=False,
		)
		frappe.db.commit()


def compute_next_run(frequency: str, schedule_time, from_dt=None) -> datetime.datetime:
	"""Next fire time strictly after ``from_dt`` (default now) at ``schedule_time``
	on the given ``frequency`` (daily/weekly/monthly)."""
	base = get_datetime(from_dt) if from_dt else now_datetime()
	secs = _time_to_seconds(schedule_time)
	cand = base.replace(hour=secs // 3600, minute=(secs % 3600) // 60, second=0, microsecond=0)
	while cand <= base:
		cand = _advance(cand, frequency)
	return cand


def _advance(dt: datetime.datetime, frequency: str) -> datetime.datetime:
	if frequency == "weekly":
		return add_to_date(dt, days=7)
	if frequency == "monthly":
		return add_to_date(dt, months=1)
	return add_to_date(dt, days=1)


def _time_to_seconds(t) -> int:
	if not t:
		return _DEFAULT_SECONDS
	if isinstance(t, datetime.timedelta):
		return int(t.total_seconds())
	parts = str(t).split(":")
	try:
		h = int(parts[0])
		m = int(parts[1]) if len(parts) > 1 else 0
		s = int(parts[2]) if len(parts) > 2 else 0
		return h * 3600 + m * 60 + s
	except (ValueError, IndexError):
		return _DEFAULT_SECONDS
