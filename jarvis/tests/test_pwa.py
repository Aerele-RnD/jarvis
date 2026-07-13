"""Tests for the mobile PWA's service-worker plumbing.

The PWA is only a PWA if its service worker actually controls the app, and that
rests on one fragile arrangement (see ``jarvis/pwa.py``):

- **The worker is reachable at the site root.** Frappe's StaticPage renderer
  refuses to serve ``.js`` out of ``www/``, so a custom page renderer serves it
  at ``/jarvis-mobile.sw.js``. A worker may only claim a scope at or below the
  path it is served from, so this root-level path is what lets it claim
  ``/jarvis-mobile`` — a worker shipped under ``/assets/jarvis/pwa/`` could only
  ever control ``/assets/jarvis/pwa/``.
- **The app's catch-all must not swallow it.** ``website_route_rules`` sends
  ``/jarvis-mobile/<path:app_path>`` to the app shell. Had the worker been
  exposed at ``/jarvis-mobile/sw.js`` it would resolve to that rule and be
  served HTML — the registration would fail with a MIME error and the PWA would
  silently stop being installable. The renderer sees the endpoint AFTER route
  rules are applied, so the only defence is that the two paths cannot collide.
- **The scope is narrow.** The header must grant ``/jarvis-mobile`` and nothing
  above it; a worker scoped to ``/`` would control the Desk.

These are exactly the invariants a well-meaning refactor of the route rules
would break without any visible error, so they are pinned here.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import set_request
from frappe.website.path_resolver import resolve_path

from jarvis.pwa import SW_ROUTE, SW_SCOPE, ServiceWorkerRenderer


def _resolve(path: str) -> str:
	"""Resolve a path the way a real HTTP request would.

	Route rules are ONLY applied when a request exists — ``evaluate_dynamic_routes``
	returns None otherwise, and ``resolve_from_map`` then hands the path straight
	back. Resolving without a request would make every assertion below pass
	vacuously, which is precisely the bug this helper exists to prevent.
	"""
	set_request(method="GET", path=f"/{path}")
	return resolve_path(path)


class TestServiceWorkerRoute(FrappeTestCase):
	def test_sw_route_is_not_swallowed_by_the_app_catch_all(self):
		"""The worker path must survive route resolution untouched.

		If this fails, /jarvis-mobile.sw.js is being rewritten to the app shell,
		the browser gets HTML where it expects JavaScript, registration dies on a
		MIME error, and the app quietly stops being installable.
		"""
		self.assertEqual(_resolve(SW_ROUTE), SW_ROUTE)

	def test_app_routes_still_resolve_to_the_shell(self):
		"""The flip side: the bare route and deep links DO reach the shell, so a
		refresh on /jarvis-mobile/c/<id> renders the app instead of 404ing."""
		self.assertEqual(_resolve("jarvis-mobile"), "jarvis_mobile")
		self.assertEqual(_resolve("jarvis-mobile/c/abc123"), "jarvis_mobile")

	def test_desk_and_desktop_spa_are_untouched(self):
		"""The renderer runs on every website request and the app owns two
		catch-alls; neither may reach across into the Desk or the /jarvis SPA."""
		self.assertEqual(_resolve("jarvis/skills"), "jarvis")
		self.assertEqual(_resolve("app"), "app")

	def test_renderer_claims_only_the_worker_path(self):
		"""can_render() runs on every website request; it must match one path."""
		self.assertTrue(ServiceWorkerRenderer(SW_ROUTE).can_render())
		for path in ("app", "jarvis", "jarvis-mobile", "jarvis-mobile/c/abc"):
			self.assertFalse(
				ServiceWorkerRenderer(path).can_render(),
				f"renderer must not claim {path!r}",
			)

	def test_worker_is_served_as_javascript_scoped_to_the_app(self):
		"""A worker served as text/html is rejected outright, and one allowed a
		scope above /jarvis-mobile could control the Desk."""
		response = ServiceWorkerRenderer(SW_ROUTE).render()

		self.assertEqual(response.status_code, 200)
		self.assertIn("javascript", response.headers["Content-Type"])
		self.assertEqual(response.headers["Service-Worker-Allowed"], SW_SCOPE)
		self.assertEqual(SW_SCOPE, "/jarvis-mobile")
		# Never stale: a cached worker pins users to an old precache manifest.
		self.assertIn("no-store", response.headers["Cache-Control"])

	def test_precached_urls_are_absolute(self):
		"""Workbox resolves precache URLs against wherever the WORKER is served
		from — the site root here, not the bundle directory. Relative entries
		would resolve to /assets/index-*.js and 404, so the build must emit them
		absolute (vite.config.js: modifyURLPrefix)."""
		sw = frappe.read_file(
			frappe.get_app_path("jarvis", "public", "pwa", "sw.js"),
		)
		self.assertIsNotNone(sw, "PWA is not built — run `npm run build-pwa`")
		self.assertIn('"/assets/jarvis/pwa/offline.html"', sw)
		self.assertNotIn('"offline.html"', sw)
