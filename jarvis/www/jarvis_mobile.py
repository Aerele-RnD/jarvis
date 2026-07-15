import frappe

from jarvis.permissions import has_jarvis_access

no_cache = 1


def get_context(context):
	# Server-side gate, same as the desktop SPA (www/jarvis.py): a user without
	# Jarvis access never gets the app shell. A Guest is sent to the Desk, which
	# in turn bounces to login — so the PWA needs no login screen of its own. (The
	# native app's QR pairing exists only because it lives on another origin; the
	# PWA is served BY the site and rides the session cookie.) A signed-in but
	# unauthorized user is sent to the branded /jarvis-no-access page instead.
	if not has_jarvis_access():
		frappe.local.flags.redirect_location = "/app" if frappe.session.user == "Guest" else "/jarvis-no-access"
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
