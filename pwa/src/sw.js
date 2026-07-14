/**
 * Jarvis PWA service worker (injectManifest source — vite-plugin-pwa injects
 * the precache list into self.__WB_MANIFEST at build).
 *
 * Scope note, and the reason this file is served from jarvis/pwa.py rather than
 * straight out of /assets: a worker's default scope is the directory it is
 * served from. Shipped as /assets/jarvis/pwa/sw.js it could only ever control
 * /assets/jarvis/pwa/ — never the app itself at /jarvis-mobile — which is the
 * trap the Frappe HR PWA falls into (its worker exists for push, and never
 * controls the app page). Frappe refuses to serve .js out of www/, so the app
 * exposes this file at the root-level path /jarvis-mobile.sw.js and main.js
 * registers it with an explicit {scope: "/jarvis-mobile"}: a script served from
 * / may claim any narrower scope, so the worker controls exactly the app and
 * nothing else — never the Desk.
 */
import { precacheAndRoute, cleanupOutdatedCaches, matchPrecache } from "workbox-precaching"
import { clientsClaim } from "workbox-core"
import { NavigationRoute, registerRoute, setCatchHandler } from "workbox-routing"
import { NetworkOnly } from "workbox-strategies"

const OFFLINE_URL = "/assets/jarvis/pwa/offline.html"

// JS/CSS/icons + the offline card. index.html is excluded at build (see
// vite.config.js): the real shell is Jinja-rendered per request.
precacheAndRoute(self.__WB_MANIFEST)
cleanupOutdatedCaches()

// Navigations always go to the network — the shell carries a fresh CSRF token
// and boot data, so serving a cached copy would hand the app a dead token.
// When the network is gone, setCatchHandler below answers with the offline card.
registerRoute(new NavigationRoute(new NetworkOnly(), { allowlist: [/^\/jarvis-mobile/] }))

// Anything the routes above threw on. A failed navigation gets the offline card
// (this is what makes the app openable from the home screen with no network);
// everything else fails as it normally would. Chat/auth calls to /api are not
// routed at all, so they never touch the cache.
setCatchHandler(async ({ request }) => {
	if (request.mode === "navigate") {
		const offline = await matchPrecache(OFFLINE_URL)
		if (offline) return offline
	}
	return Response.error()
})

// registerType: "autoUpdate" — a new build takes over on next load instead of
// leaving the user on a stale bundle behind a "reload?" prompt.
self.skipWaiting()
clientsClaim()
