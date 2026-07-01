"""Onboarding - store the admin token + container connection into Jarvis
Settings, and thin server wrappers the onboarding page calls (so the browser
never holds admin creds). admin_client returns already-unwrapped admin data."""

import json

import frappe

from jarvis import admin_client
from jarvis.exceptions import (
	AdminAuthError, AdminRateLimitedError, AdminUnreachableError,
	AdminValidationError,
)


def _require_admin_url() -> None:
	"""Raise ValidationError if no admin URL is configured deliberately.

	dev_onboard and start_signup must target a deliberately-chosen control
	plane. The admin URL resolves (admin_client._admin_url ->
	hooks.get_default_admin_url) in this order: (1) Jarvis Settings.
	jarvis_admin_url per-customer override, (2) ``jarvis_admin_url`` in
	site_config / common_site_config (via frappe.conf), (3) the hardcoded
	fallback for fresh installs. Silently falling through to (3) on a
	multi-site bench may land the wrong tenancy, so require (1) or (2) to be
	set - only (3)-alone is the fail-fast case. (1) wins when both are set.
	"""
	configured = (
		(frappe.db.get_single_value("Jarvis Settings", "jarvis_admin_url") or "").strip()
		or (frappe.conf.get("jarvis_admin_url") or "").strip()
	)
	if not configured:
		raise frappe.ValidationError(
			"No Jarvis Admin URL configured. Set Jarvis Settings -> Jarvis "
			"Admin URL, or 'jarvis_admin_url' in site_config.json, before "
			"continuing onboarding."
		)


def _require_https_site_url() -> None:
	"""Production onboarding must hand the admin an https:// site URL.

	The plugin accepts any frappe_site_url shape (transport security is the
	deployment's responsibility), so the policy guardrail lives here: the
	URL recorded at signup (``frappe.utils.get_url()``) must be https unless
	the install opted into Sandbox Mode (Jarvis Settings -> Developer
	section) - dev/LAN benches run plaintext http legitimately.
	"""
	from jarvis.dev import is_sandbox_mode

	if is_sandbox_mode():
		return
	url = frappe.utils.get_url()
	if not url.startswith("https://"):
		# frappe.throw (not a bare raise) so the wizard surfaces the message
		# instead of a generic "Something went wrong".
		frappe.throw(
			f"Production onboarding requires this site to be served over "
			f"https:// (currently {url}). Put the site behind TLS, or enable "
			f"Sandbox Mode (Jarvis Settings -> Developer section) for a "
			f"dev/sandbox install.",
			frappe.ValidationError,
		)


def _surface(fn, *args, **kwargs):
	"""Run an admin_client call; re-raise every admin-side error as a clean
	frappe.ValidationError so the onboarding page renders a red toast with
	an operator-actionable message instead of a long traceback dump.

	Sprint-3 (2026-06-16 review): the docstring promised "no traceback for
	any admin failure" but only AdminValidationError was actually caught;
	AdminUnreachableError / AdminAuthError / AdminRateLimitedError fell
	through and surfaced as raw 500s. Now ALL four are caught:

	- AdminValidationError  -> "<message>"
	- AdminAuthError        -> "admin authentication failed; check your "
	                            "site's bench-admin credentials"
	- AdminUnreachableError -> "admin is unreachable; check network / "
	                            "service status and try again"
	- AdminRateLimitedError -> "rate-limited by admin; retry in Ns" where
	                            N is the AdminRateLimitedError.retry_after_seconds
	                            (admin's response hint).
	"""
	try:
		return fn(*args, **kwargs)
	except AdminValidationError as e:
		frappe.throw(str(e))
	except AdminAuthError as e:
		frappe.throw(
			f"admin authentication failed; check the bench's admin credentials. ({e})"
		)
	except AdminUnreachableError as e:
		frappe.throw(
			f"admin is unreachable right now; try again in a moment. ({e})"
		)
	except AdminRateLimitedError as e:
		retry = e.retry_after_seconds or 0
		retry_str = f"retry in {retry}s" if retry > 0 else "retry shortly"
		frappe.throw(f"admin rate-limited the request; {retry_str}.")


def write_connection(data: dict) -> None:
	"""Persist native admin credentials + container connection into Jarvis
	Settings via db_set (no on_update creds-push retrigger during onboarding)."""
	if not isinstance(data, dict):
		return
	s = frappe.get_single("Jarvis Settings")
	if data.get("api_key"):
		s.db_set("jarvis_admin_api_key", data["api_key"])
	if data.get("api_secret"):
		s.db_set("jarvis_admin_api_secret", data["api_secret"])
	# OAuth password-grant credentials. ``customer`` is the admin-side login
	# (email, the grant username); ``customer_password`` is the durable secret
	# the bench exchanges for short-lived bearer tokens. The email arrives in
	# the signup response; the password arrives later (verified poll / flag-off
	# signup), so each is persisted independently when present.
	if data.get("customer"):
		s.db_set("jarvis_admin_customer_email", data["customer"])
	if data.get("customer_password"):
		s.db_set("jarvis_admin_customer_password", data["customer_password"])
	if data.get("agent_url"):
		s.db_set("agent_url", data["agent_url"])
	if data.get("agent_token"):
		s.db_set("agent_token", data["agent_token"])


@frappe.whitelist()
def sync_connection() -> dict:
	"""Pull the container connection from admin and store it. Daily scheduled +
	the page's 'Sync connection' button. No-op until onboarded/assigned.

	Gated on System Manager: writes admin credentials and container connection
	into Jarvis Settings (jarvis_admin_api_key, agent_url, agent_token). The
	scheduler runs as Administrator which bypasses only_for. Sprint-1 Important
	from the 2026-06-16 code review.
	"""
	frappe.only_for("System Manager")
	settings = frappe.get_single("Jarvis Settings")
	api_key = settings.get_password("jarvis_admin_api_key", raise_exception=False) or ""
	api_secret = settings.get_password("jarvis_admin_api_secret", raise_exception=False) or ""
	if not (api_key and api_secret):
		return {"synced": False, "reason": "not onboarded"}
	data = admin_client.get_connection()
	if data.get("agent_url"):
		write_connection(data)
		return {"synced": True, "tenant_status": data.get("tenant_status")}
	return {"synced": False, "tenant_status": data.get("tenant_status", "pending")}


@frappe.whitelist()
def list_plans() -> list:
	return admin_client.get_plans()


@frappe.whitelist()
def get_preset_catalog() -> list:
	"""Preset catalog for the desk onboarding step + the /ai SPA route.
	Thin wrapper over admin_client (fetch/cache/bundled fallback)."""
	return admin_client.get_preset_catalog()


@frappe.whitelist()
def start_signup(email: str, company: str, plan: str) -> dict:
	"""Guest signup → store the api_token → return the Razorpay handles for Checkout.

	Gated on System Manager (Sprint-1 Important from the 2026-06-16 code
	review): the customer signing up is configuring Jarvis for their entire
	site, which is a System Manager operation on Frappe by convention.
	Without this, a non-admin staff user could initiate a paid signup using
	a different email/company under the site's admin contract.

	Requires ``Jarvis Settings.jarvis_admin_url`` to be set first. Otherwise
	admin_client falls back to the DEFAULT_ADMIN_URL, which on a multi-site
	bench may be the wrong control plane. Fail fast with an actionable
	error instead of silently landing the wrong tenancy.

	Two response shapes depending on admin's
	``require_email_verification`` flag:
	  - flag OFF (legacy): admin returns a Razorpay order; wizard goes
	    straight to Checkout.
	  - flag ON: admin returns ``pending_verification: True`` and no
	    order; wizard shows a "check your email" screen and polls
	    ``check_signup_payment_state`` after the customer clicks the
	    magic link. Either shape persists api_key + api_secret on the
	    bench so the poll endpoint can authenticate.
	"""
	frappe.only_for("System Manager")
	_require_admin_url()
	_require_https_site_url()
	data = _surface(admin_client.signup, email, company, plan)
	# Persist whatever credentials the response carries. The guard also fires
	# on ``customer`` so the OAuth grant username is stored even if a future
	# admin response shape omits api_key/api_secret. write_connection skips
	# empty fields individually. customer_password is present only on the
	# flag-off path (verify-on defers it to the poll).
	if data.get("api_key") or data.get("api_secret") or data.get("customer"):
		write_connection({
			"api_key": data.get("api_key", ""),
			"api_secret": data.get("api_secret", ""),
			"customer": data.get("customer", ""),
			"customer_password": data.get("customer_password", ""),
		})
	return data


@frappe.whitelist()
def check_signup_payment_state() -> dict:
	"""Wizard-poll endpoint for the email-verification window.

	Calls admin's ``get_signup_payment_state`` (authenticated via the
	api_key + api_secret persisted at start_signup time) and returns the
	response unchanged. The wizard JS branches on
	``pending_verification`` to decide whether to keep showing the
	"check your email" screen or to open Razorpay Checkout.

	Gated on System Manager for the same reason as start_signup: this is
	part of the same paid-signup flow on the customer's bench.
	"""
	frappe.only_for("System Manager")
	_require_admin_url()
	data = _surface(admin_client.get_signup_payment_state)
	# On the verified poll (email confirmed) admin delivers the customer's
	# OAuth password once. Persist it so subsequent admin calls use bearer
	# auth. Absent on the not-yet-verified poll and on the flag-off path.
	if isinstance(data, dict) and data.get("customer_password"):
		write_connection({"customer_password": data["customer_password"]})
	return data


@frappe.whitelist()
def finish_payment(payload: dict | str) -> dict:
	"""Confirm Checkout success → store the returned container connection.

	Gated on System Manager: writes container connection (agent_url,
	agent_token) into Jarvis Settings.
	"""
	frappe.only_for("System Manager")
	if isinstance(payload, str):
		payload = json.loads(payload)
	data = _surface(admin_client.confirm_payment, payload)
	write_connection(data)
	return data


@frappe.whitelist()
def renew() -> dict:
	"""Existing customer initiates a renewal payment; returns the Razorpay handles
	for Checkout. The page then completes Checkout and calls finish_payment.

	Gated on System Manager: initiates a billing transaction tied to the
	site's admin account.
	"""
	frappe.only_for("System Manager")
	return _surface(admin_client.renew)


@frappe.whitelist()
def save_llm_creds(provider: str, model: str, api_key: str = "",
                   base_url: str = "", auth_mode: str = "api_key",
                   force: bool = False) -> dict:
	"""Save LLM provider/model/auth mode + (api_key when applicable) and let
	on_update re-render openclaw.json. Returns the on_update outcome
	(last_sync_status) so the page can tell the customer whether their
	agent is fully ready.

	REV-1: ``auth_mode="oauth"`` lets the OAuth poll-success path save
	without requiring an api_key - credentials live in the container's
	auth-profiles.json (pushed via the separate push_oauth_blob path).

	``force`` (REV-3, 2026-06-12): when True, bypass on_update's diff
	gate (``_classify_llm_change`` returning None when no field changed)
	so the admin/fleet-agent push fires even on a no-op save. Required
	in the complete_paste_signin path because that flow:
	  - pushes the OAuth blob (which lives in auth-profiles.json, not
	    Jarvis Settings, so the bench's diff classifier doesn't see it)
	  - then needs fleet-agent to re-render openclaw.json AND restart
	    the container so openclaw picks up the new auth profile.
	Without ``force=True``, a customer re-authorizing with the same
	provider+model gets a stale openclaw.json + no restart, and openclaw
	keeps serving the previous (broken) state. Verified live 2026-06-11.

	Gated on System Manager (Sprint-1 Important from the 2026-06-16 code
	review): a non-admin staff user could otherwise flip ``llm_base_url``
	to an attacker-controlled URL and exfiltrate chat context through
	future LLM calls.
	"""
	frappe.only_for("System Manager")
	if not provider or not model:
		raise frappe.ValidationError("provider and model are required")
	if auth_mode not in {"api_key", "oauth"}:
		raise frappe.ValidationError(f"unsupported auth_mode: {auth_mode}")
	if auth_mode == "api_key" and not api_key:
		raise frappe.ValidationError("api_key is required when auth_mode=api_key")
	s = frappe.get_single("Jarvis Settings")
	if auth_mode == "api_key":
		# API-key path: write models[0] so the table is the source of truth.
		# on_update's _on_update_unified_llm mirrors models[0] back to the
		# legacy fields (llm_provider / llm_model / llm_base_url / llm_auth_mode
		# / llm_api_key) so all downstream readers continue to work unchanged.
		#
		# We also set llm_api_key in-memory so that validate()'s
		# _validate_auth_mode_requirements passes before on_update runs (the
		# validator checks the in-memory value first, then falls back to DB).
		s.set("models", [])
		s.append("models", {
			"provider": provider,
			"model": model,
			"base_url": (base_url or "").strip(),
			"credential_type": "api_key",
			"api_key": api_key,
			"tier": "strong",
			"order": 0,
			"enabled": 1,
		})
		# Satisfy _validate_auth_mode_requirements (reads in-memory before DB).
		s.llm_api_key = api_key
	else:
		# TODO: represent direct-OAuth single-model in the models table (future)
		# For now, leave the direct-OAuth path on the legacy field write.
		# Clear any stale api_key models rows so on_update takes the legacy
		# classify/sync path rather than the unified table path (which would
		# mirror models[0].credential_type='api_key' back over the oauth mode).
		existing_enabled = [m for m in (s.get("models") or []) if m.enabled]
		if len(existing_enabled) > 1:
			frappe.throw(
				"A multi-model LLM pool is configured. Remove the extra models from your LLM settings "
				"before switching to single-model OAuth.",
				title="LLM Configuration",
			)
		s.set("models", [])
		# Also clear preset so that a stale preset doesn't leave a ghost pool
		# flag after switching to oauth (preset + 0 models → empty pool push).
		s.preset = ""
		s.llm_provider = provider
		s.llm_model = model
		s.llm_auth_mode = auth_mode
		s.llm_base_url = (base_url or "").strip()
	if force:
		# Read by on_update -> _classify_llm_change. Cleared after the
		# enqueue dispatches so a subsequent save() in the same request
		# (e.g. db_set for last_sync_status) doesn't double-fire.
		s.flags.force_admin_sync = True
	s.save(ignore_permissions=True)
	frappe.db.commit()
	# on_update writes last_sync_* via frappe.db.set_value so the
	# in-memory ``s`` doc is stale. Fetch JUST the two fields we
	# need rather than reloading the entire Singles doc (the previous
	# shape was ``frappe.get_single(...)`` then ``.get(...)`` on
	# every field - pointless re-fetch from the 2026-06-16 review).
	row = frappe.db.get_value(
		"Jarvis Settings", "Jarvis Settings",
		["last_sync_at", "last_sync_status"], as_dict=True,
	) or {}
	return {
		"last_sync_at": str(row.get("last_sync_at") or ""),
		"last_sync_status": row.get("last_sync_status") or "",
	}


@frappe.whitelist()
def get_llm_sync_status() -> dict:
	"""Lightweight poller for the onboarding + account pages.

	``Jarvis Settings.on_update`` writes ``last_sync_status = 'pending: ...'``
	synchronously, then enqueues the heavy admin call. When the background
	job finishes, the status flips to ``ok (... via admin)`` or
	``failed: ...``. The UI polls this method every few seconds to observe
	that transition.

	Returns:
	    A dict with ``last_sync_at`` (ISO string or ""), ``last_sync_status``
	    (e.g. ``pending: provisioning container``, ``ok (restart via admin)``,
	    ``failed: admin unreachable: ...``), and a convenience boolean
	    ``pending`` for client-side branching.
	"""
	s = frappe.get_single("Jarvis Settings")
	status = s.get("last_sync_status") or ""
	return {
		"last_sync_at": str(s.get("last_sync_at") or ""),
		"last_sync_status": status,
		"pending": status.startswith("pending:"),
	}


@frappe.whitelist()
def dev_onboard(email: str, company: str, plan: str) -> dict:
	"""Local Razorpay-free onboarding: dev_force_signup → store token+connection.

	Server-side gated on sandbox mode (Jarvis Settings.sandbox_mode, with
	legacy frappe.conf.developer_mode as a one-release backwards-compat
	fallback). Without the gate, this whitelisted endpoint would let any
	authenticated user skip payment - the JS-only check on
	``frappe.boot.jarvis_sandbox_mode`` is just UX, not security.

	Requires ``Jarvis Settings.jarvis_admin_url`` to be set first. Earlier
	versions auto-populated it from ``frappe.utils.get_url()``, but that
	returns the bench-wide URL (the host_name in common_site_config) instead
	of the current site URL. On a multi-site bench that quietly lands the
	wrong value into the wrong site's Jarvis Settings. Force the operator to
	set it deliberately.

	Gated on System Manager in addition to the sandbox_mode check.
	"""
	frappe.only_for("System Manager")
	from jarvis.dev import is_sandbox_mode
	if not is_sandbox_mode():
		frappe.local.response.http_status_code = 403
		frappe.throw(
			"dev_onboard requires sandbox mode. Enable it in Jarvis "
			"Settings -> Enable Sandbox Mode before retrying."
		)
	_require_admin_url()
	data = _surface(admin_client.dev_signup, email, company, plan)
	write_connection(data)
	return data
