"""Best-effort activity trail for the Agents Marketplace.

``log_activity`` writes ONE ``Jarvis Agent Activity`` row per lifecycle event
(install / uninstall / enable / disable / schedule / config / run
transitions). The doctype is deliberately LINK-FREE — Data snapshots of the
slug / installation / run names — because the uninstall cascade hard-deletes
installations, runs and findings, and the activity history must survive those
deletes without ever raising LinkExistsError. Every write is best-effort: a
failed insert lands in the Error Log and is swallowed, never allowed to break
the operation it narrates.
"""

import frappe

ACTIVITY = "Jarvis Agent Activity"


def log_activity(*, agent, agent_title, installation, action, detail=None, run=None, owner=None):
	"""Insert one activity row AS the current session user (the feed is
	owner-scoped via ``if_owner`` read, exactly like Jarvis Agent Run). Pass
	``owner`` to attribute the row to a specific user instead — e.g. the
	installation owner when the caller runs as Administrator (the scheduler) or
	as a System Manager acting on someone else's install. Never raises — any
	failure is logged server-side and the caller proceeds."""
	try:
		doc = frappe.get_doc({
			"doctype": ACTIVITY,
			"agent": agent or "",
			"agent_title": agent_title or "",
			"installation": installation or "",
			"action": action,
			"run": run or "",
			"detail": detail or "",
		})
		if owner:
			# insert() only fills owner when unset, so this sticks.
			doc.owner = owner
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
	except Exception:
		try:
			frappe.log_error(
				title="Jarvis: agent activity log failed",
				message=frappe.get_traceback(),
			)
		except Exception:
			pass
