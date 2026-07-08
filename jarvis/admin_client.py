"""HTTPS client for the Jarvis admin (jarvis_admin) app.

Authenticated calls prefer a short-lived OAuth bearer token: the bench
exchanges the customer's password (Jarvis Settings.jarvis_admin_customer_password,
username = jarvis_admin_customer_email) for an access token at admin's native
Frappe OAuth endpoint using the shared public client id `jarvis-bench`, caches
it in Redis, and sends `Authorization: Bearer <access_token>`. Customers
onboarded before OAuth (no password stored) fall back to the legacy native
api_key:api_secret (`Authorization: token <api_key>:<api_secret>`) - admin
accepts both during the migration window.

Guest calls (signup, get_plans) skip the header entirely; their admin
endpoints are @frappe.whitelist(allow_guest=True).
"""

import re
import time

import frappe
import requests

from jarvis.exceptions import (
	AdminAuthError,
	AdminRateLimitedError,
	AdminUnreachableError,
	AdminValidationError,
)


# Admin's provision_healthz_timeout_s defaults to 60s for restart operations;
# 90s leaves 30s buffer for network round-trip + handler overhead.
DEFAULT_TIMEOUT_S = 90

# OAuth password-grant config. The bench exchanges the customer's password
# (Jarvis Settings.jarvis_admin_customer_password) for short-lived bearer
# tokens against admin's native Frappe OAuth token endpoint, using the shared
# public client id. Authenticated calls prefer the bearer; calls fall back to
# the legacy api_key:api_secret when no password is stored (pre-OAuth
# customers, dual-auth migration window).
_OAUTH_CLIENT_ID = "jarvis-bench"
_OAUTH_TOKEN_PATH = "/api/method/frappe.integrations.oauth2.get_token"
_OAUTH_SCOPE = "all openid"
# Site-scoped Redis cache for the access/refresh tokens (frappe.cache() is
# per-site). Admin credentials are a per-site singleton, so one key suffices.
_OAUTH_CACHE_KEY = "jarvis:admin_oauth_token"
# Re-mint this many seconds before the cached access token's stated expiry so
# a request can't race past the boundary.
_OAUTH_EXPIRY_SKEW_S = 60
# Upper bound the cache entry lives, so the refresh token outlives the
# (~15min) access token; on entry expiry we re-mint with the password grant.
_OAUTH_CACHE_TTL_S = 24 * 60 * 60

# Cap on the cross-boundary message length. Long messages (e.g. a Frappe
# 500 with a 10KB traceback that happens to embed a token mid-frame) get
# truncated at the admin_client edge so they can't blow up
# ``last_sync_status`` (a Data field) or burn Error Log rows. Anything
# longer than this lands in Error Log only.
_MAX_MESSAGE_CHARS = 500

# Patterns to redact before any admin response text is allowed to cross
# the boundary into an Admin*Error message (which then becomes the body of
# ``last_sync_status`` via jarvis_settings.py and the Error Log via
# frappe.log_error). Even though admin's whitelisted endpoints are not
# supposed to echo secrets, defense-in-depth: a future admin handler
# raising ``frappe.throw("body was %s" % body)`` would otherwise reflect
# the request's api_key / api_secret / refresh_token straight back into
# the bench's status field. Punch-list "secret values can leak to
# last_sync_status/Error Log via upstream passthrough" from the
# 2026-06-16 cross-repo review.
_SECRET_PATTERNS = (
	# token=VALUE / api_key=VALUE / api_secret=VALUE / Bearer VALUE /
	# Authorization: Bearer VALUE / etc. Captures the credential keyword
	# + the (=|:) + the secret. We replace the whole tail with [REDACTED]
	# so the keyword survives ("AuthenticationError: api_key=[REDACTED]
	# is invalid").
	re.compile(
		r"(?i)\b("
		r"api[_-]?key|api[_-]?secret|client[_-]?secret|"
		r"access[_-]?token|refresh[_-]?token|"
		r"authorization|bearer|password|secret"
		r")\s*[=:]\s*\S+"
	),
	# OpenAI / Anthropic-style key prefixes (sk-..., sk-ant-..., etc.)
	# without an explicit keyword. Conservative threshold (20+ chars)
	# so we don't false-positive on short literals like "sk-1".
	re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
	# RFC 7519 JWTs (id_token / access_token shapes).
	re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
)


def _scrub_secrets(text: str) -> str:
	"""Strip token-shaped substrings from text crossing the admin_client
	boundary. Truncate to ``_MAX_MESSAGE_CHARS`` so a 10KB Frappe traceback
	can't pollute ``last_sync_status``.

	Idempotent: scrubbing already-scrubbed text leaves [REDACTED] markers
	intact (the patterns don't match the literal "[REDACTED]").
	"""
	if not text:
		return text
	out = text
	for pat in _SECRET_PATTERNS:
		out = pat.sub(lambda m: (
			# Keyword + "=[REDACTED]" for the labeled-credential pattern;
			# bare "[REDACTED]" for the prefix / JWT patterns (whole match
			# IS the secret).
			f"{m.group(1)}=[REDACTED]" if m.lastindex else "[REDACTED]"
		), out)
	if len(out) > _MAX_MESSAGE_CHARS:
		out = out[:_MAX_MESSAGE_CHARS] + "...[truncated]"
	return out

# DEFAULT_ADMIN_URL lives in hooks.py as a single source of truth for
# deployment-level constants; re-exported here so existing
# ``from jarvis.admin_client import DEFAULT_ADMIN_URL`` callers keep working.
# Override per-customer via ``Jarvis Settings.jarvis_admin_url``.
from jarvis.hooks import DEFAULT_ADMIN_URL  # noqa: E402  - used by _admin_url() below


def _admin_url(settings) -> str:
	# A deliberately-set site/common config ``jarvis_admin_url`` is the
	# deployment's source of truth and WINS over the ``Jarvis Settings`` field.
	# A reinstall / re-provision can leave a stale dev value (e.g.
	# "http://127.0.0.1:8000") in the doctype field; letting that mask a
	# correctly-configured site config made the admin unreachable. Resolution
	# order: site/common config -> Jarvis Settings override -> hardcoded
	# fallback. Read FRESH via frappe.conf / get_default_admin_url() so a config
	# value added after worker start is honored without a restart (the
	# module-level DEFAULT_ADMIN_URL import binds once and would miss it).
	from jarvis.hooks import get_default_admin_url
	conf_url = (frappe.conf.get("jarvis_admin_url") or "").strip().rstrip("/")
	if conf_url:
		return conf_url
	return ((settings.jarvis_admin_url or "").rstrip("/")) or get_default_admin_url().rstrip("/")


def signup(email: str, company_name: str, plan: str, coupon: str | None = None) -> dict:
	"""Guest signup against admin. Returns admin's data dict
	{api_key, api_secret, razorpay_key_id, razorpay_order_id, amount_inr}.
	Both annual and monthly are one-shot orders (manual renew - no Razorpay subscription).

	When the admin's ``Jarvis Admin Settings.require_email_verification``
	flag is ON, the response shape is:
	    {api_key, api_secret, razorpay_key_id, amount_inr, customer,
	     pending_verification: True}
	(no razorpay_order_id - the order is deferred until the customer clicks
	the magic link and the bench polls ``get_signup_payment_state``).
	"""
	body = {"email": email, "company_name": company_name, "plan": plan,
			"frappe_site_url": frappe.utils.get_url()}
	if coupon:
		body["coupon"] = coupon
	return _post_guest(path="/api/method/jarvis_admin.billing.signup.signup", body=body)


def get_signup_payment_state() -> dict:
	"""Authenticated poll. Returns one of:
	    {pending_verification: True}
	      - customer hasn't clicked the magic link yet
	    {pending_verification: False, razorpay_order_id, razorpay_key_id,
	     amount_inr}
	      - verification done; wizard can advance to Razorpay Checkout
	    {pending_verification: False, subscription_status: <other>}
	      - signup already completed (verification + payment both done)

	Uses the authenticated _post path with the api_key + api_secret the
	bench stashed at signup time. Only meaningful between the verification-
	on signup() return and the customer's click of the magic link; the
	wizard polls this on a "I've verified my email" button click.
	"""
	return _post(
		path="/api/method/jarvis_admin.billing.signup.get_signup_payment_state",
		body={},
	)


def dev_signup(email: str, company_name: str, plan: str) -> dict:
	"""Razorpay-free dev signup. Returns admin's flat dict incl. api_key + api_secret + connection."""
	return _post_guest(
		path="/api/method/jarvis_admin.billing.signup.dev_force_signup",
		body={"email": email, "company_name": company_name, "plan": plan,
			  "frappe_site_url": frappe.utils.get_url()},
	)


def get_plans() -> list:
	return _post_guest(path="/api/method/jarvis_admin.billing.signup.get_plans", body={})


# Admin-owned preset catalog (spec 3.3). Guest-safe fetch (get_plans pattern),
# cached in per-site Redis, bundled fallback so onboarding never hard-fails.
_PRESET_CATALOG_PATH = "/api/method/jarvis_admin.billing.catalog.get_preset_catalog"
_PRESET_CATALOG_CACHE_KEY = "jarvis:preset_catalog"
_PRESET_CATALOG_TTL_S = 6 * 60 * 60


def get_preset_catalog() -> list:
	"""Fetch the enabled Aerele preset catalog from admin (guest-safe), cache it,
	and fall back to the last cached copy then the bundled default so onboarding
	never hard-fails (spec L7). Never raises."""
	from jarvis._preset_catalog import BUNDLED_PRESET_CATALOG
	cache = frappe.cache()
	cached = cache.get_value(_PRESET_CATALOG_CACHE_KEY)
	if cached:
		return cached
	try:
		catalog = _post_guest(path=_PRESET_CATALOG_PATH, body={})
	except Exception:
		# "Never raises": onboarding's preset step must degrade to the bundled
		# catalog on ANY failure, not just the Admin* family. A scheme-less
		# jarvis_admin_url, for instance, raises requests.MissingSchema (a
		# RequestException that _do_post does NOT convert to an Admin* error),
		# which would otherwise 500 the whitelisted onboarding endpoint. #200
		# review #9.
		frappe.log_error(title="get_preset_catalog fell back to bundled")
		return BUNDLED_PRESET_CATALOG
	if isinstance(catalog, dict):
		catalog = catalog.get("data") or catalog.get("catalog") or catalog.get("presets") or []
	if isinstance(catalog, list) and catalog:
		cache.set_value(_PRESET_CATALOG_CACHE_KEY, catalog, expires_in_sec=_PRESET_CATALOG_TTL_S)
		return catalog
	return BUNDLED_PRESET_CATALOG


# Admin-owned speech-to-text config (voice features). Authenticated tenant
# fetch, cached in per-site Redis so chat-UI loads / transcribe calls don't
# pay an admin round-trip each time.
_STT_CONFIG_PATH = "/api/method/jarvis_admin.api.tenant.get_stt_config"
_STT_CONFIG_CACHE_KEY = "jarvis:stt_config"
# No bench-side bust on admin key rotation/disable: the success TTL is the
# propagation lag bound, so keep it short.
_STT_CONFIG_TTL_S = 300
_STT_CONFIG_MISS_TTL_S = 60
_STT_CONFIG_MISS = {"__stt_unavailable__": True}


def get_stt_config() -> dict | None:
	"""Fetch the tenant's speech-to-text config from admin
	(``{"enabled": bool, "api_key": str, "model": str}``), cache it, and
	return None on ANY failure — voice features must degrade to
	"not configured" rather than break callers (``get_chat_ui_settings``
	runs on every SPA load). Failures are negative-cached briefly so a
	slow/down admin can't make every SPA load pay a fresh round-trip.
	Never raises."""
	cache = frappe.cache()
	cached = cache.get_value(_STT_CONFIG_CACHE_KEY)
	if cached == _STT_CONFIG_MISS:
		return None
	if cached:
		return cached
	try:
		# Short timeout: this is best-effort config on a hot endpoint; a
		# slow admin must degrade to "not configured", not block the SPA.
		cfg = _post(path=_STT_CONFIG_PATH, body={}, timeout_s=5)
	except Exception:
		cache.set_value(
			_STT_CONFIG_CACHE_KEY, _STT_CONFIG_MISS, expires_in_sec=_STT_CONFIG_MISS_TTL_S
		)
		return None
	if not isinstance(cfg, dict):
		cache.set_value(
			_STT_CONFIG_CACHE_KEY, _STT_CONFIG_MISS, expires_in_sec=_STT_CONFIG_MISS_TTL_S
		)
		return None
	out = {
		"enabled": bool(cfg.get("enabled")),
		"api_key": cfg.get("api_key") or "",
		"model": cfg.get("model") or "",
	}
	cache.set_value(_STT_CONFIG_CACHE_KEY, out, expires_in_sec=_STT_CONFIG_TTL_S)
	return out


def confirm_payment(payload: dict) -> dict:
	"""POST Razorpay Checkout result; returns {agent_url, agent_token, tenant_status}."""
	return _post(path="/api/method/jarvis_admin.api.tenant.confirm_payment", body=payload)


def get_connection() -> dict:
	"""Fetch the assigned container connection (fallback / scheduled sync)."""
	return _post(path="/api/method/jarvis_admin.api.tenant.get_connection", body={})


def renew() -> dict:
	"""Existing customer pays again to extend (manual one-shot). Returns admin's
	data dict {razorpay_order_id, razorpay_key_id, amount_inr} for Checkout."""
	return _post(path="/api/method/jarvis_admin.api.tenant.renew", body={})


def post_update_llm_creds(
	provider: str, model: str, base_url: str, api_key: str,
	auth_mode: str = "api_key",
) -> dict:
	"""POST customer's new LLM creds to admin's /tenant/update-llm-creds.

	``auth_mode`` defaults to ``"api_key"`` to keep existing call sites
	source-compatible. Subscription-mode callers pass ``"subscription"`` and
	pass the OAuth access token as ``api_key``.
	"""
	# Ship the site's installed apps so admin persists them and the fleet-agent
	# scopes the tenant's persona skill families (e.g. no hrms app -> no hrms-*).
	return _post(
		path="/api/method/jarvis_admin.api.tenant.update_llm_creds",
		body={
			"provider": provider, "model": model,
			"base_url": base_url, "api_key": api_key,
			"auth_mode": auth_mode,
			"installed_apps": frappe.get_installed_apps(),
		},
	)


def post_rotate_llm_secret(secret: str) -> dict:
	"""POST a rotated LLM secret to admin's /tenant/rotate-llm-secret.

	Used by the bench-side OAuth refresh cron via _sync_via_admin("reload").
	Hot-rotates /secrets/llm.key on the container without restart.

	Raises:
		AdminRateLimitedError on HTTP 429.
		AdminAuthError, AdminUnreachableError, AdminValidationError as usual.
	"""
	return _post(
		path="/api/method/jarvis_admin.api.tenant.rotate_llm_secret",
		body={"secret": secret},
	)


def post_rotate_agent_token(new_token: str) -> dict:
	"""POST a rotated plugin agent_token to admin's /tenant/rotate-agent-token.

	C2 PR-3C orchestrator. Called from rotate_agent_token (this module's
	whitelisted bench endpoint, gated to System Manager). The bench
	generates fresh randomness, calls here, and ONLY persists locally
	when this returns success - so a partial-failure mid-rotation leaves
	the on-disk token in lockstep with what the container knows.

	Default 180s timeout matches push_oauth_blob: admin chains to
	fleet-agent's PUT /rotate-agent-token, which does a ``compose up -d``
	(container recreate) + healthz poll. Admin's bound is healthz+30s
	(default 90s); 180s gives HTTPS round-trip + response headroom.

	Raises:
	    AdminAuthError, AdminUnreachableError, AdminValidationError
	    (shares the rotate-secret 20/h bucket).
	"""
	return _post(
		path="/api/method/jarvis_admin.api.tenant.rotate_agent_token",
		body={"new_token": new_token},
		timeout_s=180,
	)


def post_push_oauth_blob(provider: str, blob: dict) -> dict:
	"""POST an openclaw OAuthCredential blob to admin → fleet-agent → container.

	Called after a successful device-code poll. The container's openclaw
	codex/gemini-cli provider reads the blob from auth-profiles.json and
	refreshes internally via pi-ai going forward.

	Timeout is bumped above the default 90s because the admin handler
	chains to fleet-agent's PUT /auth-profile, which now runs
	``openclaw doctor --fix --non-interactive`` (up to 60s, migrates the
	legacy JSON store to SQLite on openclaw 2026.6.5+) plus
	``docker compose restart`` + healthz poll. Admin's own bound is 150s;
	we give bench 180s to allow for the HTTPS round-trip and admin's
	response serialization on top of that. The earlier 90s default ran
	out at the doctor step, surfacing as the same
	"AdminUnreachableError: read timeout" we hit 2026-06-12.

	Raises:
		AdminAuthError, AdminUnreachableError, AdminValidationError
		(rate-limit shares rotate-secret's 20/h bucket).
	"""
	return _post(
		path="/api/method/jarvis_admin.api.tenant.push_oauth_blob",
		body={"provider": provider, "blob": blob},
		timeout_s=180,
	)


def post_push_custom_skills(skills: list[dict]) -> dict:
	"""POST the customer's rendered custom skills to admin → fleet → container.

	``skills`` is the list built by ``jarvis.chat.custom_skills.build_push_payload``
	(each ``{slug, description, user_invocable, body}``). The fleet-agent does a
	FULL RECONCILE (writes the desired set, removes the rest) then restarts the
	container so openclaw re-scans ``workspace/skills``. An empty list is a valid
	"remove all custom skills" reconcile.

	Timeout matches ``post_push_oauth_blob``: the admin handler chains to the
	fleet-agent's ``PUT /custom-skills`` which re-renders the entrypoint, writes
	the files and runs ``docker compose restart`` + healthz poll.

	Raises:
		AdminAuthError, AdminUnreachableError, AdminValidationError
		(rate-limit shares the rotate-secret bucket).
	"""
	return _post(
		path="/api/method/jarvis_admin.api.tenant.push_custom_skills",
		body={"skills": skills},
		timeout_s=180,
	)


def post_push_agent_skills(agent_skills: list[dict]) -> dict:
	"""POST the customer's ENABLED marketplace-agent bundles to admin -> fleet ->
	container, into the SEPARATE ``agent_skills`` reconcile namespace (adversarial
	S4: never let it evict the customer's own custom skills).

	``agent_skills`` is the list built by
	``jarvis.chat.agent_catalog.build_agent_push_payload`` (each
	``{slug, description, body}`` where ``slug`` is ``agent-<agent_slug>``). The
	fleet-agent does a FULL RECONCILE of the agent_skills dir (writes the desired
	set, removes the rest), unions ``agent-*`` into the skill allowlist, then
	restarts the container so openclaw re-scans ``workspace/skills``. An empty
	list is a valid "remove all agent skills" reconcile.

	NOTE: the admin endpoint ``jarvis_admin.api.tenant.push_agent_skills`` and the
	fleet ``PUT /v1/containers/{name}/agent-skills`` are the B5 half of this work
	(a sibling of the custom-skills chain). Until they ship this raises
	``AdminValidationError`` (unknown method), which ``apply_agents`` records as a
	terminal ``failed:`` status — the bench-side path is complete and structured
	identically to ``post_push_custom_skills``.

	Raises:
		AdminAuthError, AdminUnreachableError, AdminValidationError
		(rate-limit shares the rotate-secret bucket).
	"""
	return _post(
		path="/api/method/jarvis_admin.api.tenant.push_agent_skills",
		body={"agent_skills": agent_skills},
		timeout_s=180,
	)


def post_push_learned_skills(learned_skills: list[dict]) -> dict:
	"""POST the customer's compiled learned skills to admin -> fleet -> container,
	into the SEPARATE ``learned_skills`` reconcile namespace (Behavioural Pattern
	Learning Phase 2; adversarial S4: never let compiled behaviour bundles evict
	the customer's own custom skills or the marketplace-agent bundles).

	``learned_skills`` is the list built by
	``jarvis.learning.compiler.build_learned_push_payload`` (each
	``{slug, description, body}`` where ``slug`` is ``learned-<domain>``, matching
	the agent- item shape). The fleet-agent does a FULL RECONCILE of the
	learned_skills dir (writes the desired set, removes the rest), unions
	``learned-*`` into the skill allowlist, then restarts the container so
	openclaw re-scans ``workspace/skills``. An empty list is a valid "remove all
	learned skills" reconcile.

	Raises:
		AdminAuthError, AdminUnreachableError, AdminValidationError
		(rate-limit shares the rotate-secret bucket).
	"""
	return _post(
		path="/api/method/jarvis_admin.api.tenant.push_learned_skills",
		body={"learned_skills": learned_skills},
		timeout_s=180,
	)


def push_wiki_files(files: list[dict], delete: list | None = None,
					known_paths: list | None = None) -> dict | None:
	"""POST one batch of rendered org-wiki mirror files to admin → fleet →
	container workspace ``wiki/`` (wiki v2 mirror; see jarvis.chat.wiki_mirror).

	``files``: ``[{path, content_b64}]`` with paths RELATIVE under the wiki
	dir (e.g. ``customers/customer--acme.md``, ``index.md``); the caller keeps
	each batch under the fleet-agent's 256KB body cap. ``delete``: relative
	paths to remove. ``known_paths``: full-sync reconcile — fleet prunes wiki
	files not in the list.

	NO restart (the workspace is a live RW bind mount), so admin gives this
	relay its OWN rate bucket — it never burns the rotate-secret 20/h bucket
	the skill pushes share.

	Returns the parsed response dict (``{ok, written, deleted, pruned}``) or
	None on ANY failure: the mirror is a derived, rebuildable copy and the
	sync must degrade to "retry next sync" — never raise into the wiki save
	paths or the sync worker (which also means: no negative cache; the next
	sync should probe again immediately).
	"""
	try:
		return _post(
			path="/api/method/jarvis_admin.api.tenant.post_push_wiki_files",
			body={"files": files, "delete": delete, "known_paths": known_paths},
			timeout_s=60,
		)
	except Exception:
		frappe.log_error(
			title="admin_client: push_wiki_files failed",
			message=frappe.get_traceback(),
		)
		return None


def push_wiki_graph(payload: dict) -> dict | None:
	"""POST the computed User/Role/Org wiki-utilization graph to admin, which
	re-validates and upserts it into ``Jarvis Wiki Graph Snapshot`` (see
	jarvis.chat.wiki_graph). Own rate bucket admin-side; NOT a container op.

	Returns the parsed response dict or None on ANY failure — the graph is a
	derived, rebuildable analytics copy and the sync must degrade to "retry next
	sync", never raise into the wiki save paths or the sync worker.
	"""
	try:
		return _post(
			path="/api/method/jarvis_admin.api.tenant.post_push_wiki_graph",
			body={"graph": payload},
			timeout_s=60,
		)
	except Exception:
		frappe.log_error(
			title="admin_client: push_wiki_graph failed",
			message=frappe.get_traceback(),
		)
		return None


def get_generated_media(since_ms: int = 0) -> list[dict]:
	"""Pull recent codex ``imagegen`` output for this customer's running tenant
	container (admin → fleet → container disk). Returns a list of
	``{filename, mime, size, mtime_ms, b64}`` (capped by the fleet agent).

	Best-effort: the caller swallows failures - a missing generated image must
	never fail a chat turn. Read-only on the container (no restart).
	"""
	# _post already unwraps the admin's ``data`` envelope, so the response here
	# is the ``{"media": [...]}`` dict itself (not ``{"data": {"media": ...}}``).
	resp = _post(
		path="/api/method/jarvis_admin.api.tenant.fetch_generated_media",
		body={"since_ms": int(since_ms or 0)},
		timeout_s=60,
	)
	return (resp or {}).get("media") or []


def post_subscription_disconnect() -> dict:
	"""POST to admin to clear the customer's OAuth profile on the container.

	Idempotent - a tenant in api_key mode is a no-op success.
	"""
	return _post(
		path="/api/method/jarvis_admin.api.tenant.subscription_disconnect",
		body={},
	)


def post_update_llm_pool(*, spec: dict, api_keys: dict, oauth_blobs: dict) -> dict:
	"""POST a PoolSpec + separated secrets to admin → fleet-agent → openclaw.

	``spec``        : secret-free PoolSpec dict (name, routing_mode, models).
	``api_keys``    : mapping ref → plaintext key (e.g. {"POOL_KEY_0": "sk-..."}).
	``oauth_blobs`` : mapping account_ref → parsed OAuth blob dict.

	The admin endpoint merges the secrets with the spec before forwarding to
	fleet-agent. Implemented in T3 (jarvis_admin); this stub is the bench-side
	caller so the controller and tests can reference it before that lands.

	Raises:
		AdminAuthError, AdminUnreachableError, AdminValidationError
	"""
	return _post(
		path="/api/method/jarvis_admin.api.tenant.update_llm_pool",
		body={"spec": spec, "api_keys": api_keys, "oauth_blobs": oauth_blobs},
		timeout_s=120,
	)


def post_llm_auth_status() -> dict:
	"""Ask admin (and via admin, fleet-agent) whether the customer's
	container actually holds a usable OAuth profile right now.

	Used by the wizard / account page to gate the "Connected" UI state
	on the runtime contract rather than on the bench having sent the
	push. The on-disk file can be present without the running gateway
	seeing it (that's the bug class fleet-agent Task 1.2's restart
	closed), and the bench's last_sync_status only reflects whether the
	admin call returned 2xx - neither tells you "openclaw resolved the
	profile."

	Returns:
	    Same shape as the admin endpoint:
	    {"ok": True,
	     "data": {"auth_profile_present": bool,
	              "profile_ids": [...],
	              "default_model": str,
	              "openai_profile_expires_ms": int | None}}
	    Never includes token material.

	Raises AdminAuthError / AdminUnreachableError / AdminValidationError
	in the same shape as the other admin_client methods.
	"""
	return _post(
		path="/api/method/jarvis_admin.api.tenant.llm_auth_status",
		body={},
	)


def get_llm_usage() -> dict:
	"""Curated real Bifrost usage for the customer's tenant (monitor tab).
	Chain: fleet-agent /llm-usage -> admin api.tenant.get_llm_usage -> here.
	Raises AdminAuthError / AdminUnreachableError / AdminValidationError."""
	return _post(path="/api/method/jarvis_admin.api.tenant.get_llm_usage", body={})


def pair_chat_device(public_key: str, device_id: str,
                     *, request_timeout_s: int = 30) -> dict:
	"""POST customer's chat device pubkey to admin; admin asks the fleet-agent
	to write a PairedDevice record into the customer's openclaw container and
	returns the issued bearer device-token. Customer keeps the private key.

	Sprint-2 plumb-through (2026-06-16 review): ``request_timeout_s`` is
	the budget the bench asks admin to allow for its admin -> fleet-agent
	leg. Defaults to 30s (matches admin's prior hardcoded value). Admin
	clamps to [5, 90] on its side so an over-large value can't push the
	overall HTTPS round-trip past the bench's outer DEFAULT_TIMEOUT_S=90.

	The outer HTTPS round-trip timeout (bench -> admin) stays at
	DEFAULT_TIMEOUT_S=90s; that's the absolute upper bound on this call.
	"""
	return _post(
		path="/api/method/jarvis_admin.api.tenant.pair_chat_device",
		body={
			"public_key": public_key,
			"device_id": device_id,
			"request_timeout_s": request_timeout_s,
		},
	)


def get_account_summary() -> dict:
	"""Fetch the customer's plan + validity + upgrade-eligible plans. Used by
	the /jarvis-account page to render plan summary and the upgrade picker."""
	return _post(
		path="/api/method/jarvis_admin.api.account.get_account_summary",
		body={},
	)


def preview_upgrade(target_plan: str) -> dict:
	"""Get the prorated amount for upgrading to ``target_plan`` (no order
	created). Used by the upgrade plan picker so each plan card shows the
	live-computed amount before the customer commits."""
	return _post(
		path="/api/method/jarvis_admin.api.account.preview_upgrade",
		body={"target_plan": target_plan},
	)


def start_upgrade(target_plan: str) -> dict:
	"""Create a prorated Razorpay order for the upgrade and return the
	Razorpay handles ({razorpay_order_id, razorpay_key_id, amount_inr,
	target_plan}). The order's notes carry the upgrade intent for
	confirm_payment to pick up after Razorpay Checkout completes."""
	return _post(
		path="/api/method/jarvis_admin.api.account.start_upgrade",
		body={"target_plan": target_plan},
	)


def _oauth_token_request(admin_url: str, grant: dict) -> dict | None:
	"""POST a form-encoded grant to admin's OAuth token endpoint. Returns the
	token dict ({access_token, refresh_token, expires_in, ...}) on success, or
	None on any failure (network, non-JSON, non-200, missing access_token) so
	the caller can fall back. Never raises; never logs token material.

	Form-encoded (not JSON): Frappe's get_token reads ``request.form``.
	"""
	payload = {**grant, "client_id": _OAUTH_CLIENT_ID, "scope": _OAUTH_SCOPE}
	url = admin_url + _OAUTH_TOKEN_PATH
	try:
		resp = requests.post(
			url,
			data=payload,
			headers={"Content-Type": "application/x-www-form-urlencoded"},
			timeout=DEFAULT_TIMEOUT_S,
		)
	except requests.RequestException as e:
		# Broad catch (not just ConnectionError/Timeout) so SSL errors, redirect
		# loops, etc. return None and the caller falls back rather than crashing.
		# A requests exception repr carries url/host, never the POST body.
		frappe.log_error(
			title="admin_client: oauth token network error",
			message=f"url={url!r} grant={grant.get('grant_type')!r} error={e!r}",
		)
		return None
	try:
		token = resp.json()
	except ValueError:
		frappe.log_error(
			title="admin_client: oauth token non-JSON response",
			message=f"grant={grant.get('grant_type')!r} status={resp.status_code}",
		)
		return None
	if resp.status_code != 200 or not isinstance(token, dict) or not token.get("access_token"):
		# invalid_grant / invalid_client / expired-or-revoked refresh, etc.
		# Log the error code only (never the credentials) for triage.
		err = token.get("error") if isinstance(token, dict) else None
		frappe.log_error(
			title="admin_client: oauth token request rejected",
			message=(
				f"grant={grant.get('grant_type')!r} "
				f"status={resp.status_code} error={err!r}"
			),
		)
		return None
	return token


def _cache_oauth_token(token: dict) -> None:
	ttl = int(token.get("expires_in") or 0)
	if ttl <= 0:
		# No usable lifetime advertised. Don't cache an instantly-stale token:
		# the freshness check would always miss and re-mint on every call,
		# storming the token endpoint. The caller still uses this token once.
		return
	frappe.cache().set_value(
		_OAUTH_CACHE_KEY,
		{
			"access_token": token["access_token"],
			"refresh_token": token.get("refresh_token"),
			"access_expires_at": time.time() + ttl,
		},
		expires_in_sec=_OAUTH_CACHE_TTL_S,
	)


def _admin_access_token(settings, admin_url: str, *,
						force_refresh: bool = False) -> str | None:
	"""Return a valid OAuth bearer access token for admin, or None when the
	bench has no OAuth credentials stored (pre-OAuth customer -> caller falls
	back to api_key:api_secret).

	Serves a cached access token until shortly before expiry. On a miss, tries
	the refresh token (best-effort), then the password grant (the durable
	bootstrap). ``force_refresh`` bypasses the cache to re-mint after a 401.
	"""
	username = (settings.jarvis_admin_customer_email or "").strip()
	# Password field -> get_password decrypts the real value out of __Auth.
	password = (settings.get_password(
		"jarvis_admin_customer_password", raise_exception=False
	) or "").strip()
	if not username or not password:
		return None

	cache = frappe.cache()
	cached = {} if force_refresh else (cache.get_value(_OAUTH_CACHE_KEY) or {})
	access = cached.get("access_token")
	if access and (cached.get("access_expires_at", 0) - _OAUTH_EXPIRY_SKEW_S) > time.time():
		return access

	token = None
	refresh = cached.get("refresh_token")
	if refresh:
		token = _oauth_token_request(admin_url, {
			"grant_type": "refresh_token", "refresh_token": refresh,
		})
	if not token:
		token = _oauth_token_request(admin_url, {
			"grant_type": "password", "username": username, "password": password,
		})
	if not token:
		return None
	_cache_oauth_token(token)
	return token["access_token"]


def _post(path: str, body: dict, *,
		  timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
	"""Authenticated POST. Prefers a short-lived OAuth bearer token (password
	grant, cached in Redis) and falls back to the legacy native
	api_key:api_secret for customers onboarded before OAuth. Raises
	AdminAuthError when neither credential set is available.

	Folds the Settings + admin-URL read here so public wrappers stay one-liners
	(one Settings load per call).
	"""
	settings = frappe.get_single("Jarvis Settings")
	admin_url = _admin_url(settings)

	# Preferred path: OAuth bearer. Retry once on a token rejection (revoked,
	# or raced past the ~15min cap) by re-minting. If the retry is still
	# rejected, drop the cached token so the next call re-mints cleanly
	# instead of replaying the poisoned one, then fall through to the legacy
	# credential below.
	access_token = _admin_access_token(settings, admin_url)
	if access_token:
		headers = {
			"Authorization": f"Bearer {access_token}",
			"Content-Type": "application/json",
		}
		try:
			return _do_post(admin_url + path, body, headers, timeout_s, admin_url)
		except AdminAuthError as token_err:
			# A 403 is an authorization denial, not a stale token. Re-minting
			# would yield a token for the same customer principal (which backs
			# both the bearer and the legacy api_key:api_secret), so the retry
			# and the legacy fallback would just replay into the same 403 while
			# storming the token endpoint and evicting the cache on every call.
			# Surface it as-is; only a 401 (revoked / over-cap token) re-mints.
			if token_err.status_code == 403:
				raise
			access_token = _admin_access_token(settings, admin_url, force_refresh=True)
			if access_token:
				headers["Authorization"] = f"Bearer {access_token}"
				try:
					return _do_post(admin_url + path, body, headers, timeout_s, admin_url)
				except AdminAuthError as retry_err:
					# Same rule on the retry: a 403 is terminal; a 401 falls
					# through to the legacy credential below.
					if retry_err.status_code == 403:
						raise
			# Both bearer attempts rejected (or re-mint failed) - clear the
			# cache and fall through to legacy.
			frappe.cache().delete_value(_OAUTH_CACHE_KEY)

	# Legacy native api_key:api_secret (pre-OAuth customers / OAuth fallback).
	# Both are Password fields - attribute access returns the masked "*****"
	# placeholder; get_password decrypts the real value out of __Auth.
	api_key = (settings.get_password(
		"jarvis_admin_api_key", raise_exception=False
	) or "").strip()
	api_secret = (settings.get_password(
		"jarvis_admin_api_secret", raise_exception=False
	) or "").strip()
	if not api_key or not api_secret:
		raise AdminAuthError(
			"not onboarded (Jarvis Settings: no OAuth password and no api_key/secret)"
		)
	headers = {
		"Authorization": f"token {api_key}:{api_secret}",
		"Content-Type": "application/json",
	}
	return _do_post(admin_url + path, body, headers, timeout_s, admin_url)


def _post_guest(path: str, body: dict, *,
				timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
	"""Unauthenticated POST (signup, get_plans). No Authorization header.
	Fetches the admin URL override from Settings internally so callers
	don't have to."""
	settings = frappe.get_single("Jarvis Settings")
	admin_url = _admin_url(settings)
	headers = {"Content-Type": "application/json"}
	return _do_post(admin_url + path, body, headers, timeout_s, admin_url)


def _extract_frappe_message(payload: dict) -> str:
	"""Pull the user-facing message out of a Frappe exception envelope.

	Frappe encodes user-visible alerts under `_server_messages` (a JSON-encoded
	list of JSON-encoded dicts with a `message` key). When that's empty, fall
	back to the `exception` string and strip the leading `module.path.ClassName: `
	prefix so we don't leak Python internals to the operator.

	The return value is always scrubbed for token-shaped substrings before it
	crosses the admin_client boundary - see _scrub_secrets for the patterns.
	Punch-list "secret values can leak to last_sync_status/Error Log via
	upstream passthrough" from the 2026-06-16 cross-repo review.
	"""
	import json as _json
	raw = (payload.get("_server_messages") or "").strip()
	if raw:
		try:
			messages = _json.loads(raw)
			if messages:
				first = _json.loads(messages[0]) if isinstance(messages[0], str) else messages[0]
				msg = (first or {}).get("message") or ""
				if msg:
					return _scrub_secrets(msg)
		except (ValueError, TypeError):
			pass
	exc = (payload.get("exception") or "").strip()
	if ":" in exc:
		return _scrub_secrets(exc.split(":", 1)[1].strip())
	return _scrub_secrets(exc or payload.get("exc_type") or "unknown admin error")


def _envelope_error_message(envelope) -> str:
	"""Pull ``error.message`` out of an admin envelope and run it through
	_scrub_secrets. Single bottleneck for the err.get('message') paths -
	every Admin*Error message we construct from upstream-controlled text
	flows through here."""
	if not isinstance(envelope, dict):
		return ""
	err = envelope.get("error", {}) or {}
	return _scrub_secrets(err.get("message") or "")


def _do_post(url: str, body: dict, headers: dict, timeout_s: int, admin_url: str) -> dict:
	try:
		resp = requests.post(url, json=body, headers=headers, timeout=timeout_s)
	except (requests.ConnectionError, requests.Timeout) as e:
		# Log the raw network detail to Error Log for operator triage;
		# surface only the bench-friendly summary on the exception (the
		# UI renders this verbatim). Punch-list item from the 2026-06-16
		# review: error bodies were re-raised verbatim, leaking
		# internal exception strings (paths, urllib internals) into
		# the customer-facing toast.
		frappe.log_error(
			title="admin_client: network error",
			message=f"url={url!r} error={e!r}",
		)
		raise AdminUnreachableError("admin is unreachable; check network / service status") from e

	try:
		payload = resp.json()
	except ValueError:
		# Non-JSON response usually = Frappe 5xx HTML error page or an
		# upstream proxy 502/504. The body could include internal
		# paths/tracebacks; log it but don't surface to the bench UI.
		frappe.log_error(
			title="admin_client: non-JSON response",
			message=f"url={url!r} status={resp.status_code} body={resp.text[:1000]!r}",
		)
		raise AdminUnreachableError(
			f"admin returned non-JSON response (status {resp.status_code})"
		)

	envelope = payload.get("message", payload) if isinstance(payload, dict) else payload

	# Pre-extract the clean message + exc_type if Frappe wrapped a raised
	# exception. The status-based branches below prefer this clean text
	# over the raw envelope when available.
	exc_type = (
		payload.get("exc_type", "") if isinstance(payload, dict) else ""
	)
	clean = _extract_frappe_message(payload) if (
		isinstance(payload, dict) and (exc_type or payload.get("_server_messages"))
	) else ""

	def _envelope_message() -> str:
		# _envelope_error_message already scrubs; clean is already scrubbed
		# (it came from _extract_frappe_message). Falling back to "" is fine.
		return _envelope_error_message(envelope) or clean or ""

	# Status-based routing for the three unambiguous wire signals.
	# The 2026-06-16 review caught that the previous shape ran the
	# exc_type allowlist BEFORE the status check, so a 429 admin
	# response with exc_type="RateLimitedError" (not in the allowlist)
	# fell through to AdminUnreachableError - losing the rate-limit
	# category entirely. 401/403/429 always win.
	if resp.status_code in (401, 403):
		raise AdminAuthError(
			_envelope_message() or f"admin returned {resp.status_code}",
			status_code=resp.status_code,
		)
	if resp.status_code == 429:
		err = (envelope or {}).get("error", {}) if isinstance(envelope, dict) else {}
		raise AdminRateLimitedError(
			_envelope_error_message(envelope) or clean or "rate_limited",
			retry_after_seconds=int(err.get("retry_after_seconds") or 0),
		)

	# Frappe-wrapped raised exception with no unambiguous status. Route
	# by exc_type allowlist; default to AdminUnreachableError when the
	# class isn't recognised.
	if exc_type:
		if exc_type in ("ValidationError", "DuplicateEntryError", "DoesNotExistError"):
			raise AdminValidationError(clean)
		# AuthenticationError ~ a token/credential failure (retry-eligible, 401);
		# PermissionError ~ an authorization denial (terminal, 403). Tag the
		# status so _post re-mints on the former but surfaces the latter as-is.
		if exc_type == "AuthenticationError":
			raise AdminAuthError(clean, status_code=401)
		if exc_type == "PermissionError":
			raise AdminAuthError(clean, status_code=403)
		# Unknown exc_type. Log it (so we learn what other admin error
		# classes to add to the allowlist) but don't embed admin_url +
		# raw exception class in the user-facing message.
		frappe.log_error(
			title=f"admin_client: unrecognised exc_type={exc_type!r}",
			message=f"url={url!r} clean={clean!r}",
		)
		raise AdminUnreachableError(
			clean or f"admin returned an unrecognised error: {exc_type}"
		)
	# Sprint-3 PR-8 (2026-06-16 review): a 4xx response with the
	# structured envelope ({"ok": false, "error": {...}}) is a
	# user-input / business-rule error, NOT an "admin is unreachable"
	# condition. The previous shape raised AdminUnreachableError for
	# both 4xx envelopes AND genuine 5xx / network failures, which
	# made _surface() in onboarding.py show "admin is unreachable;
	# try again" for things like "no subscription found" or
	# "downgrade not supported" - misleading and unhelpful.
	#
	# Route by HTTP status:
	#   4xx + envelope -> AdminValidationError (clean text to UI)
	#   5xx + envelope -> AdminUnreachableError (network / admin-down)
	#   200 with ok:false (rare; some endpoints inline failure) -> AdminUnreachableError
	if resp.status_code >= 400:
		msg = _envelope_error_message(envelope)
		if not msg:
			# No structured ``error.message`` -> log the raw body but
			# don't include it in the user-facing exception.
			frappe.log_error(
				title=f"admin_client: {resp.status_code} with no error.message",
				message=f"url={url!r} body={resp.text[:1000]!r}",
			)
			msg = f"admin returned {resp.status_code}"
		if 400 <= resp.status_code < 500:
			raise AdminValidationError(msg)
		raise AdminUnreachableError(
			f"admin returned a {resp.status_code} error: {msg}"
		)
	if isinstance(envelope, dict) and not envelope.get("ok", True):
		err = envelope.get("error", {}) or {}
		code = err.get("code") or "?"
		msg = _envelope_error_message(envelope)
		if not msg:
			frappe.log_error(
				title="admin_client: 200 with ok:false but no error.message",
				message=f"url={url!r} body={resp.text[:1000]!r}",
			)
			msg = "admin returned an error envelope with no message"
		# Keep code in the message (stable identifier admin_client
		# callers + ops can grep for). admin_url is intentionally
		# omitted - the bench knows where it's pointing.
		raise AdminUnreachableError(f"{code}: {msg}")
	return envelope.get("data", envelope) if isinstance(envelope, dict) else envelope
