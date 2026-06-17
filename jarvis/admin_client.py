"""HTTPS client for the Jarvis admin (jarvis_admin) app.

Authenticated calls use Frappe's native api_key:api_secret. The customer's
bench reads both from Jarvis Settings (set at signup) and sends them as
`Authorization: token <api_key>:<api_secret>`.

Guest calls (signup, get_plans) skip the header entirely; their admin
endpoints are @frappe.whitelist(allow_guest=True).
"""

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

# DEFAULT_ADMIN_URL lives in hooks.py as a single source of truth for
# deployment-level constants; re-exported here so existing
# ``from jarvis.admin_client import DEFAULT_ADMIN_URL`` callers keep working.
# Override per-customer via ``Jarvis Settings.jarvis_admin_url``.
from jarvis.hooks import DEFAULT_ADMIN_URL  # noqa: E402, F401


def _admin_url(settings) -> str:
	return ((settings.jarvis_admin_url or "").rstrip("/")) or DEFAULT_ADMIN_URL


def signup(email: str, company_name: str, plan: str, coupon: str | None = None) -> dict:
	"""Guest signup against admin. Returns admin's data dict
	{api_key, api_secret, razorpay_key_id, razorpay_order_id, amount_inr}.
	Both annual and monthly are one-shot orders (manual renew - no Razorpay subscription)."""
	settings = frappe.get_single("Jarvis Settings")
	body = {"email": email, "company_name": company_name, "plan": plan,
			"frappe_site_url": frappe.utils.get_url()}
	if coupon:
		body["coupon"] = coupon
	return _post_guest(path="/api/method/jarvis_admin.billing.signup.signup",
					   body=body, admin_url=_admin_url(settings))


def dev_signup(email: str, company_name: str, plan: str) -> dict:
	"""Razorpay-free dev signup. Returns admin's flat dict incl. api_key + api_secret + connection."""
	settings = frappe.get_single("Jarvis Settings")
	return _post_guest(path="/api/method/jarvis_admin.billing.signup.dev_force_signup",
					   body={"email": email, "company_name": company_name, "plan": plan,
							 "frappe_site_url": frappe.utils.get_url()},
					   admin_url=_admin_url(settings))


def get_plans() -> list:
	settings = frappe.get_single("Jarvis Settings")
	return _post_guest(path="/api/method/jarvis_admin.billing.signup.get_plans",
					   body={}, admin_url=_admin_url(settings))


def confirm_payment(payload: dict) -> dict:
	"""POST Razorpay Checkout result; returns {agent_url, agent_token, tenant_status}."""
	settings = frappe.get_single("Jarvis Settings")
	return _post(path="/api/method/jarvis_admin.api.tenant.confirm_payment",
				 body=payload, admin_url=_admin_url(settings))


def get_connection() -> dict:
	"""Fetch the assigned container connection (fallback / scheduled sync)."""
	settings = frappe.get_single("Jarvis Settings")
	return _post(path="/api/method/jarvis_admin.api.tenant.get_connection",
				 body={}, admin_url=_admin_url(settings))


def renew() -> dict:
	"""Existing customer pays again to extend (manual one-shot). Returns admin's
	data dict {razorpay_order_id, razorpay_key_id, amount_inr} for Checkout."""
	settings = frappe.get_single("Jarvis Settings")
	return _post(path="/api/method/jarvis_admin.api.tenant.renew",
				 body={}, admin_url=_admin_url(settings))


def post_update_llm_creds(
	provider: str, model: str, base_url: str, api_key: str,
	auth_mode: str = "api_key",
) -> dict:
	"""POST customer's new LLM creds to admin's /tenant/update-llm-creds.

	``auth_mode`` defaults to ``"api_key"`` to keep existing call sites
	source-compatible. Subscription-mode callers pass ``"subscription"`` and
	pass the OAuth access token as ``api_key``.
	"""
	settings = frappe.get_single("Jarvis Settings")
	return _post(
		path="/api/method/jarvis_admin.api.tenant.update_llm_creds",
		body={
			"provider": provider, "model": model,
			"base_url": base_url, "api_key": api_key,
			"auth_mode": auth_mode,
		},
		admin_url=_admin_url(settings),
	)


def post_rotate_llm_secret(secret: str) -> dict:
	"""POST a rotated LLM secret to admin's /tenant/rotate-llm-secret.

	Used by the bench-side OAuth refresh cron via _sync_via_admin("reload").
	Hot-rotates /secrets/llm.key on the container without restart.

	Raises:
		AdminRateLimitedError on HTTP 429.
		AdminAuthError, AdminUnreachableError, AdminValidationError as usual.
	"""
	settings = frappe.get_single("Jarvis Settings")
	return _post(
		path="/api/method/jarvis_admin.api.tenant.rotate_llm_secret",
		body={"secret": secret},
		admin_url=_admin_url(settings),
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
	settings = frappe.get_single("Jarvis Settings")
	return _post(
		path="/api/method/jarvis_admin.api.tenant.rotate_agent_token",
		body={"new_token": new_token},
		admin_url=_admin_url(settings),
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
	settings = frappe.get_single("Jarvis Settings")
	return _post(
		path="/api/method/jarvis_admin.api.tenant.push_oauth_blob",
		body={"provider": provider, "blob": blob},
		admin_url=_admin_url(settings),
		timeout_s=180,
	)


def post_subscription_disconnect() -> dict:
	"""POST to admin to clear the customer's OAuth profile on the container.

	Idempotent - a tenant in api_key mode is a no-op success.
	"""
	settings = frappe.get_single("Jarvis Settings")
	return _post(
		path="/api/method/jarvis_admin.api.tenant.subscription_disconnect",
		body={},
		admin_url=_admin_url(settings),
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
	settings = frappe.get_single("Jarvis Settings")
	return _post(
		path="/api/method/jarvis_admin.api.tenant.llm_auth_status",
		body={},
		admin_url=_admin_url(settings),
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
	settings = frappe.get_single("Jarvis Settings")
	return _post(
		path="/api/method/jarvis_admin.api.tenant.pair_chat_device",
		body={
			"public_key": public_key,
			"device_id": device_id,
			"request_timeout_s": request_timeout_s,
		},
		admin_url=_admin_url(settings),
	)


def get_account_summary() -> dict:
	"""Fetch the customer's plan + validity + upgrade-eligible plans. Used by
	the /jarvis-account page to render plan summary and the upgrade picker."""
	settings = frappe.get_single("Jarvis Settings")
	return _post(
		path="/api/method/jarvis_admin.api.account.get_account_summary",
		body={}, admin_url=_admin_url(settings),
	)


def preview_upgrade(target_plan: str) -> dict:
	"""Get the prorated amount for upgrading to ``target_plan`` (no order
	created). Used by the upgrade plan picker so each plan card shows the
	live-computed amount before the customer commits."""
	settings = frappe.get_single("Jarvis Settings")
	return _post(
		path="/api/method/jarvis_admin.api.account.preview_upgrade",
		body={"target_plan": target_plan}, admin_url=_admin_url(settings),
	)


def start_upgrade(target_plan: str) -> dict:
	"""Create a prorated Razorpay order for the upgrade and return the
	Razorpay handles ({razorpay_order_id, razorpay_key_id, amount_inr,
	target_plan}). The order's notes carry the upgrade intent for
	confirm_payment to pick up after Razorpay Checkout completes."""
	settings = frappe.get_single("Jarvis Settings")
	return _post(
		path="/api/method/jarvis_admin.api.account.start_upgrade",
		body={"target_plan": target_plan}, admin_url=_admin_url(settings),
	)


def _post(path: str, body: dict, admin_url: str,
		  timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
	"""Authenticated POST. Reads native api_key + api_secret from Jarvis
	Settings. Raises AdminAuthError early if either is empty."""
	settings = frappe.get_single("Jarvis Settings")
	# Both are Password fields - attribute access would return the masked
	# "*****" placeholder Frappe stores in the row. get_password decrypts
	# the real value out of __Auth.
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
	headers = {
		"Authorization": f"token {api_key}:{api_secret}",
		"Content-Type": "application/json",
	}
	return _do_post(admin_url + path, body, headers, timeout_s, admin_url)


def _post_guest(path: str, body: dict, admin_url: str,
				timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
	"""Unauthenticated POST (signup, get_plans). No Authorization header."""
	headers = {"Content-Type": "application/json"}
	return _do_post(admin_url + path, body, headers, timeout_s, admin_url)


def _extract_frappe_message(payload: dict) -> str:
	"""Pull the user-facing message out of a Frappe exception envelope.

	Frappe encodes user-visible alerts under `_server_messages` (a JSON-encoded
	list of JSON-encoded dicts with a `message` key). When that's empty, fall
	back to the `exception` string and strip the leading `module.path.ClassName: `
	prefix so we don't leak Python internals to the operator."""
	import json as _json
	raw = (payload.get("_server_messages") or "").strip()
	if raw:
		try:
			messages = _json.loads(raw)
			if messages:
				first = _json.loads(messages[0]) if isinstance(messages[0], str) else messages[0]
				msg = (first or {}).get("message") or ""
				if msg:
					return msg
		except (ValueError, TypeError):
			pass
	exc = (payload.get("exception") or "").strip()
	if ":" in exc:
		return exc.split(":", 1)[1].strip()
	return exc or payload.get("exc_type") or "unknown admin error"


def _do_post(url: str, body: dict, headers: dict, timeout_s: int, admin_url: str) -> dict:
	try:
		resp = requests.post(url, json=body, headers=headers, timeout=timeout_s)
	except (requests.ConnectionError, requests.Timeout) as e:
		raise AdminUnreachableError(f"admin {admin_url}: {e}") from e

	try:
		payload = resp.json()
	except ValueError:
		raise AdminUnreachableError(
			f"admin {admin_url} returned non-JSON (status {resp.status_code})"
		)

	# Frappe wraps any exception raised inside a whitelisted endpoint into an
	# envelope with `exc_type`. We surface those before the generic 4xx/5xx
	# branches so user-input errors (ValidationError, DuplicateEntryError,
	# DoesNotExistError) reach the page as clean text instead of a traceback dump.
	if isinstance(payload, dict) and payload.get("exc_type"):
		clean = _extract_frappe_message(payload)
		exc_type = payload.get("exc_type", "")
		if exc_type in ("ValidationError", "DuplicateEntryError", "DoesNotExistError"):
			raise AdminValidationError(clean)
		if exc_type in ("AuthenticationError", "PermissionError"):
			raise AdminAuthError(clean)
		raise AdminUnreachableError(f"admin {admin_url}: {clean}")

	envelope = payload.get("message", payload) if isinstance(payload, dict) else payload

	if resp.status_code in (401, 403):
		err = (envelope or {}).get("error", {}) if isinstance(envelope, dict) else {}
		raise AdminAuthError(err.get("message") or f"admin returned {resp.status_code}")
	if resp.status_code == 429:
		err = (envelope or {}).get("error", {}) if isinstance(envelope, dict) else {}
		raise AdminRateLimitedError(
			err.get("message") or "rate_limited",
			retry_after_seconds=int(err.get("retry_after_seconds") or 0),
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
		err = (envelope or {}).get("error", {}) if isinstance(envelope, dict) else {}
		msg = err.get("message") or resp.text[:200] or f"admin returned {resp.status_code}"
		if 400 <= resp.status_code < 500:
			raise AdminValidationError(msg)
		raise AdminUnreachableError(
			f"admin {admin_url} returned error: "
			f"{err.get('code', '?')}: {msg}"
		)
	if isinstance(envelope, dict) and not envelope.get("ok", True):
		err = envelope.get("error", {}) or {}
		raise AdminUnreachableError(
			f"admin {admin_url} returned error: "
			f"{err.get('code', '?')}: {err.get('message', resp.text[:200])}"
		)
	return envelope.get("data", envelope) if isinstance(envelope, dict) else envelope
