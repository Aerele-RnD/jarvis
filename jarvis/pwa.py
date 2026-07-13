"""Serve the PWA's service worker from the site root, so it can control the app.

A service worker may only claim a scope at or below the path it is served from.
The PWA's bundle lives at /assets/jarvis/pwa/, so a worker shipped alongside it
could only ever control /assets/jarvis/pwa/ — never the app itself, which Frappe
serves at /jarvis-mobile. (This is the trap the Frappe HR PWA falls into: its
worker is registered from /assets/hrms/frontend/sw.js and so never controls
/hrms. It works there because that worker exists for Firebase push, not offline.)

The usual fix — drop sw.js at the web root — is closed off in Frappe: the
StaticPage renderer explicitly refuses to serve ``js`` out of an app's ``www``
folder (UNSUPPORTED_STATIC_PAGE_TYPES). So the app registers a custom page
renderer instead. Custom renderers are tried FIRST (PathResolver.resolve), and
they see the endpoint AFTER website_route_rules have been applied — which is why
the worker is exposed at the root-level ``/jarvis-mobile.sw.js`` rather than
``/jarvis-mobile/sw.js``: the latter would be swallowed by the app's own
``/jarvis-mobile/<path:app_path>`` catch-all and served the HTML shell.

Served from the root, the worker is free to claim any narrower scope, and
main.js registers it with an explicit ``{scope: "/jarvis-mobile"}`` — so it
controls exactly the PWA and never the Desk at /app.
"""

import os

import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer

# Root-level, deliberately NOT under /jarvis-mobile/ (see module docstring).
SW_ROUTE = "jarvis-mobile.sw.js"

# The only scope this worker is allowed to claim. Sent as a response header so
# the browser permits the narrower registration even though the script is served
# from the root.
SW_SCOPE = "/jarvis-mobile"


def _sw_path() -> str:
	"""Absolute path of the built worker (vite-plugin-pwa emits it into outDir)."""
	return os.path.join(frappe.get_app_path("jarvis"), "public", "pwa", "sw.js")


class ServiceWorkerRenderer(BaseRenderer):
	def can_render(self) -> bool:
		# BaseRenderer strips the leading slash off the path.
		return self.path == SW_ROUTE and os.path.isfile(_sw_path())

	def render(self):
		with open(_sw_path(), "rb") as f:
			data = f.read()

		# build_response guesses the content type from the path, so the ".js"
		# suffix earns the right mimetype; a worker served as text/html is
		# rejected outright.
		return self.build_response(
			data,
			headers={
				"Service-Worker-Allowed": SW_SCOPE,
				# The worker is the one file that must never be served stale: a
				# cached copy would pin users to an old precache manifest and the
				# bundle it names.
				"Cache-Control": "no-cache, no-store, must-revalidate",
			},
		)
