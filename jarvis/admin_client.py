"""HTTPS client for the Jarvis admin (jarvis_admin) app.

Authenticated calls use Frappe's native api_key:api_secret. The customer's
bench reads both from Jarvis Settings (set at signup) and sends them as
`Authorization: token <api_key>:<api_secret>`.

Guest calls (signup, get_plans) skip the header entirely; their admin
endpoints are @frappe.whitelist(allow_guest=True).
"""

import re

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
	return ((settings.jarvis_admin_url or "").rstrip("/")) or DEFAULT_ADMIN_URL


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
	return _post(
		path="/api/method/jarvis_admin.api.tenant.update_llm_creds",
		body={
			"provider": provider, "model": model,
			"base_url": base_url, "api_key": api_key,
			"auth_mode": auth_mode,
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


def post_subscription_disconnect() -> dict:
	"""POST to admin to clear the customer's OAuth profile on the container.

	Idempotent - a tenant in api_key mode is a no-op success.
	"""
	return _post(
		path="/api/method/jarvis_admin.api.tenant.subscription_disconnect",
		body={},
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


def _post(path: str, body: dict, *,
		  timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
	"""Authenticated POST. Reads native api_key + api_secret + the admin URL
	override from Jarvis Settings. Raises AdminAuthError early if either
	credential is empty.

	Previously each public wrapper open-coded
	``settings = frappe.get_single(...)`` + ``_admin_url(settings)`` before
	calling _post (which then re-fetched Settings internally for the
	credentials). Folding the settings read here means callers shrink to
	``return _post(path=..., body=...)`` - one Settings load per call
	instead of two. Punch-list item from the 2026-06-16 review.
	"""
	settings = frappe.get_single("Jarvis Settings")
	# Both credential fields are Password fields - attribute access would
	# return the masked "*****" placeholder Frappe stores in the row.
	# get_password decrypts the real value out of __Auth.
	api_key = (settings.get_password(
		"jarvis_admin_api_key", raise_exception=False
	) or "").strip()
	api_secret = settings.get_password(
		"jarvis_admin_api_secret", raise_exception=False
	) or ""
	if not api_key or not api_secret:
		raise AdminAuthError(
			"not onboarded (Jarvis Settings: admin api_key + api_secret empty)"
		)
	admin_url = _admin_url(settings)
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
		raise AdminAuthError(_envelope_message() or f"admin returned {resp.status_code}")
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
		if exc_type in ("AuthenticationError", "PermissionError"):
			raise AdminAuthError(clean)
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
