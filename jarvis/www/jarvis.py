import frappe

no_cache = 1


def get_context(context):
	# frappe-ui's jinjaBootData plugin emits `window["<key>"] = {{ boot[key]|tojson }}`
	# for each key in `boot`, so the SPA gets window.csrf_token (frappe-ui reads it
	# for the X-Frappe-CSRF-Token header) and window.site_name (socket.js). Auth is
	# the session cookie — no custom token flow. Every value must be a plain JSON
	# type (a LocalProxy like frappe.local.lang breaks |tojson).
	context.boot = {
		"csrf_token": frappe.sessions.get_csrf_token(),
		"site_name": str(frappe.local.site),
		"default_route": "/jarvis",
		"is_system_manager": "System Manager" in frappe.get_roles(),
		# Site timezone for the SPA's dayjs config — shipping it in boot lets
		# AppShell configure systemTimezone synchronously instead of gating the
		# first routed render on a settings request.
		"time_zone": frappe.utils.get_system_timezone(),
	}
	frappe.db.commit()
	return context
