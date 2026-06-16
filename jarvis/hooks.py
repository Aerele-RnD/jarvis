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


def _extract_gemini_cli_secret_from_node_modules() -> str:
	"""Best-effort: locate the gemini-cli npm package alongside this app and
	grep its bundled source for the OAuth client_secret. Returns "" if the
	package isn't installed, the value can't be located, or any IO error.

	The expected install location is ``<app>/node_modules/@google/gemini-cli``
	relative to this file. Run ``npm install`` in the customer app's root
	(``apps/jarvis/``) after bench-getting the app to seed it.

	gemini-cli's bundle/ ships chunks up to ~16 MB each, so we iterate
	line-by-line instead of slurping. The secret appears as a single-line
	literal (`var OAUTH_CLIENT_SECRET = "GOCSPX-..."`), so a per-line scan
	finds it without holding more than a line in memory."""
	import os
	import re
	try:
		app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		pkg_root = os.path.join(app_root, "node_modules", "@google", "gemini-cli")
		if not os.path.isdir(pkg_root):
			return ""
		# Direct match against `GOCSPX-...` literal - tight, fast, and ignores
		# the surrounding context (`var OAUTH_CLIENT_SECRET = "..."`,
		# `client_secret: "..."`, JSON, whatever).
		pattern = re.compile(rb'"(GOCSPX-[A-Za-z0-9_-]+)"')
		for root, _dirs, files in os.walk(pkg_root):
			for name in files:
				if not name.endswith((".js", ".cjs", ".mjs", ".json")):
					continue
				path = os.path.join(root, name)
				try:
					with open(path, "rb") as f:
						for line in f:
							m = pattern.search(line)
							if m:
								return m.group(1).decode("utf-8", errors="ignore")
				except (OSError, IOError):
					continue
	except Exception:
		return ""
	return ""


def get_oauth_client_secret(provider: str) -> str:
	"""Return the client_secret for confidential-client OAuth flows. Empty
	string for PKCE-only providers (OpenAI codex). For Google Gemini falls
	back to extracting from the installed @google/gemini-cli package if no
	env var override was supplied."""
	val = OAUTH_CLIENT_SECRETS.get(provider, "")
	if val:
		return val
	if provider == "Google Gemini":
		return _extract_gemini_cli_secret_from_node_modules()
	return ""

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "jarvis",
# 		"logo": "/assets/jarvis/logo.png",
# 		"title": "Jarvis",
# 		"route": "/jarvis",
# 		"has_permission": "jarvis.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_css = ["/assets/jarvis/css/jarvis-brand.css"]
# app_include_js = "/assets/jarvis/js/jarvis.js"

# include js, css files in header of web template
# web_include_css = "/assets/jarvis/css/jarvis.css"
# web_include_js = "/assets/jarvis/js/jarvis.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "jarvis/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "jarvis/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "jarvis.utils.jinja_methods",
# 	"filters": "jarvis.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "jarvis.install.before_install"
# after_install = "jarvis.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "jarvis.uninstall.before_uninstall"
# after_uninstall = "jarvis.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "jarvis.utils.before_app_install"
# after_app_install = "jarvis.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "jarvis.utils.before_app_uninstall"
# after_app_uninstall = "jarvis.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "jarvis.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "jarvis.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

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
	],
}

# Testing
# -------

# before_tests = "jarvis.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "jarvis.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "jarvis.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "jarvis.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["jarvis.utils.before_request"]
# after_request = ["jarvis.utils.after_request"]

# Job Events
# ----------
# before_job = ["jarvis.utils.before_job"]
# after_job = ["jarvis.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"jarvis.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# Require all whitelisted methods to have type annotations
require_type_annotated_api_methods = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

