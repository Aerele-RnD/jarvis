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
#   1. ``jarvis_admin_url`` in site_config.json (or common_site_config.json) -
#      the deployment's source of truth (resolved in admin_client, not here)
#   2. ``Jarvis Settings.jarvis_admin_url`` per-customer override
#   3. this hardcoded fallback for fresh installs
# Site config outranks the doctype field so a stale value left in Jarvis
# Settings by a reinstall cannot mask a correctly-configured control plane.
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
#      inside that dir after bench-getting the app). NOTE: the dep is pinned
#      to an EXACT version (SEC-008, Aerele-RnD/jarvis-admin#192), so this
#      no longer auto-tracks upstream rotations - when Google rotates the
#      embedded secret, either set the env override (step 1) or deliberately
#      bump the pin in package.json + package-lock.json (keep it in lockstep
#      with the fleet-agent entrypoint's GEMINI_CLI_VERSION pin).
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
app_include_js = ["jarvis_immersive.bundle.js", "jarvis_widget.bundle.js", "jarvis_onboarding_llm.bundle.js", "jarvis_onboarding_banner.bundle.js"]

# Separate frappe-ui Vue SPA (apps/jarvis/frontend) served at /jarvis. The
# catch-all routes every /jarvis/* deep link to the www/jarvis page so the
# SPA's vue-router (history mode) can handle them.
website_route_rules = [
	{"from_route": "/jarvis/<path:app_path>", "to_route": "jarvis"},
]

# The agents marketplace lives at the SPA route /jarvis/agents; keep the
# friendlier top-level /jarvis-agents spelling working as a redirect.
website_redirects = [
	{"source": "/jarvis-agents", "target": "/jarvis/agents"},
]

# Session hooks
# --------------

# 2026-07 latency plan, Phase 1.4: kick off a (debounced) prefix warm-up on
# login so the provider prompt cache is warm before the chat page even loads.
on_session_creation = ["jarvis.chat.prewarm.warm_on_login"]

# Keep the Agents Marketplace catalog (Jarvis Agent Listing) in lockstep with
# the BUNDLED jarvis/agents/registry.json on every migrate (never a runtime
# fetch — bundles are reviewed deploy artifacts, adversarial S2).
after_migrate = [
	"jarvis.chat.agent_catalog.after_migrate",
	# Behavioural pattern learning: seed Jarvis Pattern Detector State rows
	# from the detector registry (best-effort; never blocks a migrate).
	"jarvis.learning.bootstrap.after_migrate",
	# Voice & Wiki: seed the Settings Check defaults (row-existence probe;
	# an unset Check reads 0 on v16, so defaults must be materialized).
	"jarvis.learning.voice_facts.after_migrate",
	# Wiki v2: seed the Knowledge Wiki User/Manager roles (idempotent;
	# best-effort). Migrate follows a fresh install, so this covers both.
	"jarvis.learning.roles.after_migrate",
]

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		"*/5 * * * *": [
			"jarvis.chat.stale_scan.scan_and_mark_errored",
			# 2026-07 latency plan, Phase 1.4: was */30, which left the
			# provider prompt cache (5-10 min retention) cold for most of
			# each half-hour. Every 5 min + a 4-min cooldown in prewarm.py
			# keeps the prefix warm continuously while there is recent chat
			# activity (the function itself gates on activity).
			"jarvis.chat.prewarm.keep_warm_if_active",
		],
		"*/2 * * * *": [
			"jarvis.chat.turn_recovery.recover_pending_turns",
		],
		"*/15 * * * *": [
			# Behavioural pattern learning tick. Hooks cron is app-static
			# (per-site rows are reset on migrate), so the window is
			# self-enforced: the tick bails on the site_config kill switch,
			# the enabled flag, self-host and outside-window times.
			"jarvis.learning.orchestrator.tick",
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
		# Fire any scheduled macros whose next_run_at has passed.
		"jarvis.chat.macro_scheduler.run_due_macros",
		# Fire any due scheduled auditor agents. Identity-safe (runs each audit
		# as its owner, never Administrator); budget-capped; advances only on a
		# successful enqueue. See jarvis/chat/agent_scheduler.py.
		"jarvis.chat.agent_scheduler.run_due_agent_audits",
		# Recovery-completeness batch: spike alarm if the 24h recovered-turn
		# rate is high enough to suggest a sick gateway (deduped to roughly
		# once a day inside the function).
		"jarvis.chat.turn_recovery.recovery_rate_watch",
	],
	"daily": [
		# Session lifecycle Phase 1: rotate dormant conversations' openclaw
		# sessions and reap orphaned throwaway sessions (title/prewarm,
		# deleted conversations). Batch-capped; bench history untouched.
		"jarvis.chat.session_lifecycle.rotate_dormant_sessions",
		"jarvis.onboarding.sync_connection",
		# C2 (2026-06-16 review): nudge operators when the bench's
		# agent_token is approaching or past its configured max age.
		# Daily is plenty - the warning window is 7 days.
		"jarvis.oauth.cron.check_agent_token_age",
		# Daily voice-note sweep: mine New voice notes into learned-pattern
		# candidates + wiki updates (self-gating; see jarvis/learning/voice_facts.py).
		"jarvis.learning.voice_facts.process_daily",
		# Skills-area rework (DESIGN.md section 3): daily backstops for the
		# Personalise question bank. materialize_questions_daily mints questions
		# for Proposed learned-pattern findings that missed the immediate
		# lifecycle hook (per-user daily cap + dedupe); materialize_rule_questions
		# fans admin-authored question rules out to in-scope users (uncapped).
		"jarvis.learning.questions.materialize_questions_daily",
		"jarvis.learning.questions.materialize_rule_questions",
		# Daily push of the User/Role/Org wiki-utilization graph to admin (the
		# DB-only scope/role tiers; admin overlays telemetry activity). Not on
		# every wiki save — too chatty for an analytics view.
		"jarvis.chat.wiki_graph.sync",
		# Daily append of org-wide graph totals to Jarvis Wiki Graph History (one
		# row/day) — the measured Knowledge-Evolution series for the Evolution tab.
		"jarvis.chat.wiki_graph.record_history_snapshot",
	],
	"weekly": [
		# Wiki v2 health check: deterministic lint over Active pages
		# (contradictions, staleness, orphans, near-duplicate titles);
		# summary lands on the Jarvis Settings RO fields. Swallows errors.
		"jarvis.learning.wiki_lint.scheduled_lint",
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

# Org-scope wiki pages are mirrored as markdown into the tenant container
# workspace; every page write/delete enqueues a debounced mirror sync (the
# handler filters to Org scope itself and no-ops when the tenant is
# unreachable — it never raises into the save path).
_WIKI_MIRROR_SYNC = "jarvis.chat.wiki_mirror.on_wiki_page_change"
doc_events["Jarvis Wiki Page"] = {
	"after_insert": _WIKI_MIRROR_SYNC,
	"on_update": _WIKI_MIRROR_SYNC,
	"on_trash": _WIKI_MIRROR_SYNC,
}

# Skills-area rework (DESIGN.md section 3): an active Personalise question rule
# (re)materializes its questions to in-scope users on save, in addition to the
# daily sweep. The handler enqueues a deduped after-commit job (never blocks the
# save, inactive rules no-op).
doc_events["Jarvis Personalise Question Rule"] = {
	"on_update": "jarvis.learning.questions.on_rule_update",
}

# ---------------------------------------------------------------------------
# Wiki page scoping (wiki v2)
# ---------------------------------------------------------------------------
# Org/Role/User visibility for Jarvis Wiki Page, enforced at the ORM: list
# queries via permission_query_conditions, per-doc access via has_permission.
# Matrix + SQL fragments live in jarvis/chat/wiki_permissions.py.
permission_query_conditions = {
	"Jarvis Wiki Page": "jarvis.chat.wiki_permissions.wiki_page_query_conditions",
}
has_permission = {
	"Jarvis Wiki Page": "jarvis.chat.wiki_permissions.has_wiki_page_permission",
}

# ---------------------------------------------------------------------------
# Chat doctype ownership scoping (security review PART 1, TASK 7)
# ---------------------------------------------------------------------------
# Row-level owner scoping for the chat doctypes at the ORM, so generic REST
# (/api/resource, frappe.client.*, reportview) and every future endpoint
# inherit it automatically instead of relying on a hand-rolled owner check in
# each whitelisted function. Conversation/Voice scope by the row owner;
# Message/Approval scope by the LINKED conversation's owner (+ DocShare for
# Approval). Matrix + SQL fragments live in jarvis/chat/chat_permissions.py.
# The doctype permission rows carry role "Jarvis User" (not "All"), so the role
# is genuinely load-bearing: revoking it denies all four via REST.
permission_query_conditions.update({
	"Jarvis Conversation": "jarvis.chat.chat_permissions.conversation_query_conditions",
	"Jarvis Chat Message": "jarvis.chat.chat_permissions.message_query_conditions",
	"Jarvis Approval Request": "jarvis.chat.chat_permissions.approval_query_conditions",
	"Jarvis Voice Note": "jarvis.chat.chat_permissions.voice_note_query_conditions",
})
has_permission.update({
	"Jarvis Conversation": "jarvis.chat.chat_permissions.has_conversation_permission",
	"Jarvis Chat Message": "jarvis.chat.chat_permissions.has_message_permission",
	"Jarvis Approval Request": "jarvis.chat.chat_permissions.has_approval_permission",
	"Jarvis Voice Note": "jarvis.chat.chat_permissions.has_voice_note_permission",
})

