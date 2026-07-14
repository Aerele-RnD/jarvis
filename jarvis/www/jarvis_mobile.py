import frappe

from jarvis.permissions import has_jarvis_access

no_cache = 1


def get_context(context):
	# Guests DO get the shell — they land on the app's own /jarvis-mobile/login.
	#
	# Bouncing them to /app (what this used to do) breaks the installed app: the
	# manifest scope is /jarvis-mobile, and a standalone PWA that navigates out of
	# its scope is handed to the browser. So an expired session meant the app
	# kicked you into a Chrome tab showing the Desk login — which is exactly why
	# HRMS's shell is guest-renderable and its router owns a Login route.
	#
	# A signed-in user WITHOUT Jarvis access is a different case: they have a Desk,
	# so send them to it rather than showing a login form they're already past.
	if frappe.session.user != "Guest" and not has_jarvis_access():
		frappe.local.flags.redirect_location = "/app"
		raise frappe.Redirect

	# frappe-ui's jinjaBootData plugin emits `window["<key>"] = {{ boot[key]|tojson }}`
	# per key, so the app gets window.csrf_token (frappe-ui sends it as the
	# X-Frappe-CSRF-Token header) and window.site_name (socket.js). Every value
	# must be a plain JSON type — a LocalProxy breaks |tojson.
	context.boot = {
		"csrf_token": frappe.sessions.get_csrf_token(),
		"site_name": str(frappe.local.site),
		"default_route": "/jarvis-mobile",
		# Rendered on the Account screen without costing a request.
		"frappe_user_id": frappe.session.user,
		"frappe_full_name": frappe.utils.get_fullname(frappe.session.user),
	}
	frappe.db.commit()
	return context
