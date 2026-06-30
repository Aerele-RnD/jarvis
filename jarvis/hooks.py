app_name = "jarvis"
app_title = "Jarvis"
app_publisher = "Aerele"
app_description = "AI superpowers for Frappe/ERPNext"
app_email = "navin@aerele.in"
app_license = "MIT"


# ---------------------------------------------------------------------------
# Per-session bootinfo
# ---------------------------------------------------------------------------
# Frappe calls this once per page load. We use it to expose
# ``frappe.boot.jarvis_sandbox_mode`` so JS can branch on sandbox state
# without a round-trip back to the server.
boot_session = "jarvis.boot.set_jarvis_boot"

# ---------------------------------------------------------------------------
# Deployment constants
# ---------------------------------------------------------------------------
# Default URL of the Jarvis Cloud control plane the customer bench targets
# for signup, billing, plan list, container connection, and account summary.
#
# Resolution order (highest precedence first):
#   1. ``Jarvis Settings.jarvis_admin_url`` per-customer override
#      (resolved in admin_client, not here)
#   2. ``jarvis_admin_url`` in site_config.json (or common_site_config.json)
#   3. this hardcoded fallback for fresh installs
#
# Rebranding the deployment? Set ``jarvis_admin_url`` in site config, or
# change this string + ship a new release.
# (``DEFAULT_ADMIN_URL`` is re-exported by ``jarvis.admin_client`` so existing
# imports keep working - resolved lazily via module __getattr__ below.)
_DEFAULT_ADMIN_URL_FALLBACK = "https://admin.jarvis.aerele.in"


def get_default_admin_url() -> str:
	"""Bench-wide default admin URL.

	Reads ``jarvis_admin_url`` from site config via ``frappe.conf``; falls
	back to the hardcoded default when the key is absent or empty. Resolve
	this lazily at call time - ``frappe.conf`` is only populated once a site
	is initialized, which is not guaranteed at hooks.py import time."""
	import frappe

	val = (frappe.conf.get("jarvis_admin_url") or "").strip()
	return val or _DEFAULT_ADMIN_URL_FALLBACK


def __getattr__(name: str):
	# Lazy resolution so ``jarvis.hooks.DEFAULT_ADMIN_URL`` reads site config
	# on access instead of being frozen at import time. Note: a bare
	# ``from jarvis.hooks import DEFAULT_ADMIN_URL`` still binds once at the
	# importer's import time, so prefer calling ``get_default_admin_url()``
	# directly where freshness matters.
	if name == "DEFAULT_ADMIN_URL":
		return get_default_admin_url()
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# ---------------------------------------------------------------------------
# OAuth client IDs - one per supported chat-subscription provider
# ---------------------------------------------------------------------------
# These are openclaw's hardcoded CLI client IDs. We use them (not Aerele-owned
# PKCE clients) so the refresh tokens our device flow issues are compatible
# with pi-ai's refresh path inside the container - openclaw's codex provider
# refreshes against the same client_id we used to mint.
#
# Source:
#   OpenAI: openclaw/extensions/openai/openai-codex-device-code.ts:5
#   Google Gemini: bundled with @google/gemini-cli; override via env if it drifts.
#
# Anthropic Claude is deliberately absent - openclaw has no compatible
# adapter for Claude Pro/Max subscriptions.
def _env_or_default(name: str, default: str) -> str:
	import os
	return (os.environ.get(name, "") or "").strip() or default


OAUTH_CLIENT_IDS = {
	"OpenAI": _env_or_default(
		"JARVIS_OPENAI_CODEX_OAUTH_CLIENT_ID",
		"app_EMoamEEZ73f0CkXaXp7hrann",
	),
	"Google Gemini": _env_or_default(
		"JARVIS_GEMINI_CLI_OAUTH_CLIENT_ID",
		# Bundled gemini-cli client_id (extract from upstream if drift detected).
		# Operators set the env var if our embedded default goes stale.
		"681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com",
	),
}


def get_oauth_client_id(provider: str) -> str:
	"""Lookup helper for jarvis.oauth code paths."""
	if provider not in OAUTH_CLIENT_IDS:
		raise ValueError(f"No OAuth client registered for provider {provider!r}")
	return OAUTH_CLIENT_IDS[provider]


# OAuth client_secrets. Required for "confidential client" flows even when
# PKCE is in play - Google's gemini-cli is one (its /token endpoint returns
# `HTTP 400: client_secret is missing` without it). OpenAI's codex CLI flow
# is pure PKCE so the secret stays empty there. Treat these as public-by-
# design (distributed with the upstream CLI), not as real secrets. Operators
# override via env when upstream rotates.
#
# Resolution order for "Google Gemini":
#   1. JARVIS_GEMINI_CLI_OAUTH_CLIENT_SECRET env var (operator override)
#   2. Extract from the gemini-cli npm package shipped as a runtime dep of
#      this app (see apps/jarvis/package.json - install with `npm install`
#      inside that dir after bench-getting the app). This auto-tracks
#      upstream rotations.
#   3. Empty -> the token exchange fails with the explicit
#      `client_secret is missing` so the operator knows to install + restart.
OAUTH_CLIENT_SECRETS = {
	"OpenAI": _env_or_default("JARVIS_OPENAI_CODEX_OAUTH_CLIENT_SECRET", ""),
	"Google Gemini": _env_or_default("JARVIS_GEMINI_CLI_OAUTH_CLIENT_SECRET", ""),
}


def get_oauth_client_secret(provider: str) -> str:
	"""Return the client_secret for confidential-client OAuth flows. Empty
	string for PKCE-only providers (OpenAI codex). For Google Gemini falls
	back to extracting from the installed @google/gemini-cli package if no
	env var override was supplied."""
	val = OAUTH_CLIENT_SECRETS.get(provider, "")
	if val:
		return val
	if provider == "Google Gemini":
		# Imported lazily so the node_modules walk only runs when a
		# Google OAuth call asks for it.
		from jarvis.oauth.gemini_cli_secret import extract_gemini_cli_secret
		return extract_gemini_cli_secret()
	return ""

# Includes in <head>
# ------------------
# Brand styling for the Desk shell (loaded on every desk page).
app_include_css = ["/assets/jarvis/css/jarvis-brand.css"]
app_include_js = ["jarvis_immersive.bundle.js", "jarvis_widget.bundle.js"]

# Separate frappe-ui Vue SPA (apps/jarvis/frontend) served at /jarvis. The
# catch-all routes every /jarvis/* deep link to the www/jarvis page so the
# SPA's vue-router (history mode) can handle them.
website_route_rules = [
	{"from_route": "/jarvis/<path:app_path>", "to_route": "jarvis"},
]

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		"*/5 * * * *": [
			"jarvis.chat.stale_scan.scan_and_mark_errored",
		],
	},
	"hourly": [
		# Sprint-3 (2026-06-16 review): bench has no way to know if the
		# container's OAuth profile silently went away (refresh-token
		# failure, operator clear, re-provision without re-push). Hourly
		# reconciliation keeps last_sync_status honest so the UI can
		# render a "reconnect" banner instead of "Connected" until the
		# user hits a ProviderAuthError mid-chat.
		"jarvis.oauth.cron.poll_oauth_refresh_status",
	],
	"daily": [
		"jarvis.onboarding.sync_connection",
		# C2 (2026-06-16 review): nudge operators when the bench's
		# agent_token is approaching or past its configured max age.
		# Daily is plenty - the warning window is 7 days.
		"jarvis.oauth.cron.check_agent_token_age",
	],
}

# Python type annotations on whitelisted endpoints
# ------------------------------------------------
# Auto-update controller files with type annotations + require all
# whitelisted methods to be type-annotated. Both are required by the
# Sprint-1 type-safety pass on the customer-facing endpoints.
export_python_type_annotations = True
require_type_annotated_api_methods = True

# ---------------------------------------------------------------------------
# Schema-cache invalidation
# ---------------------------------------------------------------------------
# get_schema caches each DocType's schema in Redis with a short TTL. Bust that
# cache the moment a schema-defining doc changes, so the agent never builds a
# write off a stale field list inside the TTL window (a Custom Field added via
# Customize Form must show up immediately, not 5 minutes later).
_CLEAR_SCHEMA_CACHE = "jarvis.tools.get_schema.clear_schema_cache"
doc_events = {
	dt: {"on_update": _CLEAR_SCHEMA_CACHE, "on_trash": _CLEAR_SCHEMA_CACHE}
	for dt in ("DocType", "Custom Field", "Property Setter", "Workflow")
}

