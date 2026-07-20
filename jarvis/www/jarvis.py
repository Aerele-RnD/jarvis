import frappe

from jarvis.permissions import has_jarvis_access, has_jarvis_admin_access

no_cache = 1


def get_context(context):
	# Server-side gate: the SPA route is authoritative, so a user without Jarvis
	# access never gets the app shell. A Guest is sent to the Desk (/app), which
	# in turn redirects to login — preserving the guest→login bounce. A signed-in
	# but unauthorized user is sent to the branded /jarvis-no-access page instead.
	# Follows Frappe's www redirect idiom.
	if not has_jarvis_access():
		frappe.local.flags.redirect_location = (
			"/app" if frappe.session.user == "Guest" else "/jarvis-no-access"
		)
		raise frappe.Redirect

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
		# UI gate for the tenant-admin usage pane (design section 2). True for
		# System Managers too. Client gate is UX-only — every admin API
		# re-checks require_jarvis_admin server-side.
		"is_jarvis_admin": has_jarvis_admin_access(),
		# Native Frappe per-user theme (Light/Dark/Automatic); the SPA maps it to
		# light/dark/system so theme roams across devices without a Jarvis field.
		"jarvis_desk_theme": frappe.db.get_value("User", frappe.session.user, "desk_theme") or "Automatic",
		# NOTE: no `has_jarvis_access` boot flag — the guard above already
		# redirected anyone without access, so it would always be True here.
		# Site timezone for the SPA's dayjs config — shipping it in boot lets
		# AppShell configure systemTimezone synchronously instead of gating the
		# first routed render on a settings request.
		"time_zone": frappe.utils.get_system_timezone(),
	}
	frappe.db.commit()
	return context
