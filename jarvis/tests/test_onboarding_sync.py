"""Tests for jarvis.onboarding sync + wrappers (admin_client mocked)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import onboarding


def _set_token(value, secret="secret"):
	"""Set both native credentials for tests that exercise the authenticated
	admin path. value="" clears them (simulates 'not onboarded').

	Clearing must also drop the __Auth rows: the production write path
	(write_connection -> set_settings_password) stores the secret in __Auth
	with a masked column, so a column-only db_set("") would let get_password
	fall back to a previous test's __Auth value."""
	from frappe.utils.password import remove_encrypted_password

	s = frappe.get_single("Jarvis Settings")
	s.db_set("jarvis_admin_api_key", value)
	s.db_set("jarvis_admin_api_secret", secret if value else "")
	s.db_set("agent_url", "")
	if not value:
		remove_encrypted_password("Jarvis Settings", "Jarvis Settings", "jarvis_admin_api_key")
		remove_encrypted_password("Jarvis Settings", "Jarvis Settings", "jarvis_admin_api_secret")
	frappe.db.commit()


# Fields these tests write to. Snapshot in setUp, restore in tearDown so
# tests run against a real site (e.g. jarvis.localhost) don't clobber the
# operator's actual onboarded state - Frappe Singles aren't transactionally
# rolled back between tests.
_SNAPSHOTTED_FIELDS = (
	"jarvis_admin_url",
	"jarvis_admin_api_key",
	"jarvis_admin_api_secret",
	"jarvis_admin_customer_email",
	"jarvis_admin_customer_password",
	"agent_url",
	"agent_token",
)


def _snapshot_settings() -> dict:
	s = frappe.get_single("Jarvis Settings")
	snap = {}
	for f in _SNAPSHOTTED_FIELDS:
		# Password fields → get_password; plain → attribute. Both safe.
		v = (
			s.get_password(f, raise_exception=False)
			if f.endswith(("_key", "_secret", "_token", "_password"))
			else s.get(f)
		)
		snap[f] = v or ""
	return snap


def _restore_settings(snap: dict) -> None:
	"""Restore the snapshot. Password fields also get their __Auth row
	dropped: the production write path stores secrets there (masked column),
	and restoring only the column would leave a test's secret readable via
	get_password's __Auth fallback in the NEXT test. The snapshot value
	itself is written to the column (get_password short-circuits on a
	non-masked column value), matching this helper's original semantics."""
	from frappe.utils.password import remove_encrypted_password

	for f, v in snap.items():
		if f.endswith(("_key", "_secret", "_token", "_password")):
			remove_encrypted_password("Jarvis Settings", "Jarvis Settings", f)
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", f, v)
	frappe.db.commit()


class TestSyncConnection(FrappeTestCase):
	def setUp(self):
		self._snap = _snapshot_settings()

	def tearDown(self):
		_restore_settings(self._snap)

	def test_sync_writes_connection_when_assigned(self):
		_set_token("tok")
		with patch(
			"jarvis.onboarding.admin_client.get_connection",
			return_value={
				"agent_url": "ws://localhost:19000",
				"agent_token": "k",
				"tenant_status": "running",
			},
		):
			out = onboarding.sync_connection()
		self.assertTrue(out["synced"])
		self.assertEqual(frappe.get_single("Jarvis Settings").agent_url, "ws://localhost:19000")

	def test_sync_noop_when_pending(self):
		_set_token("tok")
		with patch(
			"jarvis.onboarding.admin_client.get_connection",
			return_value={"agent_url": "", "tenant_status": "pending"},
		):
			out = onboarding.sync_connection()
		self.assertFalse(out["synced"])

	def test_sync_skips_when_not_onboarded(self):
		import frappe.model.document

		with (
			patch.object(frappe.model.document.Document, "get_password", return_value=""),
			patch(
				"jarvis.onboarding.admin_client.get_connection",
				side_effect=AssertionError("admin must not be called when not onboarded"),
			),
		):
			out = onboarding.sync_connection()
		self.assertFalse(out["synced"])
		self.assertEqual(out["reason"], "not onboarded")

	def test_dev_onboard_writes_native_credentials_and_connection(self):
		_set_token("")
		frappe.db.set_value(
			"Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "http://admin.example.com"
		)
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", 1)
		frappe.db.commit()
		with patch(
			"jarvis.onboarding.admin_client.dev_signup",
			return_value={
				"customer": "C1",
				"api_key": "k2",
				"api_secret": "s2",
				"agent_url": "ws://localhost:19002",
				"agent_token": "tok",
			},
		):
			onboarding.dev_onboard("e@x.com", "Co", "Annual Plan")
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.get_password("jarvis_admin_api_key"), "k2")
		self.assertEqual(s.get_password("jarvis_admin_api_secret"), "s2")
		self.assertEqual(s.agent_url, "ws://localhost:19002")

	def test_dev_onboard_throws_when_admin_url_blank(self):
		"""dev_onboard no longer auto-populates jarvis_admin_url. Earlier
		versions defaulted it to frappe.utils.get_url(), which on a multi-site
		bench returns the bench default URL (host_name in
		common_site_config) instead of the current site's URL - that quietly
		landed the wrong value into the wrong site's Jarvis Settings. The
		operator now sets the URL explicitly; a blank field fails fast with
		an actionable error."""
		_set_token("")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "")
		frappe.db.commit()
		with (
			patch.dict(frappe.local.conf, {"jarvis_admin_url": ""}),
			patch("jarvis.onboarding.admin_client.dev_signup") as mock_signup,
		):
			with self.assertRaises(frappe.ValidationError):
				onboarding.dev_onboard("e2@x.com", "Co", "Annual Plan")
			mock_signup.assert_not_called()

	def test_dev_onboard_uses_config_admin_url_when_field_blank(self):
		"""Blank Jarvis Settings.jarvis_admin_url but site/common config
		provides jarvis_admin_url: the guard treats config as a deliberate
		source, so onboarding proceeds instead of failing fast."""
		_set_token("")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", 1)
		frappe.db.commit()
		with (
			patch.dict(frappe.local.conf, {"jarvis_admin_url": "http://conf-admin.local"}),
			patch(
				"jarvis.onboarding.admin_client.dev_signup",
				return_value={"api_key": "k", "api_secret": "s", "agent_url": "ws://h:1", "agent_token": "t"},
			) as mock_signup,
		):
			onboarding.dev_onboard("e5@x.com", "Co", "Annual Plan")
			mock_signup.assert_called_once()

	def test_dev_onboard_preserves_existing_admin_url(self):
		"""Pre-set jarvis_admin_url stays untouched - dev_onboard never
		writes to the field anymore."""
		_set_token("")
		frappe.db.set_value(
			"Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "http://other-admin.local"
		)
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", 1)
		frappe.db.commit()
		try:
			with patch(
				"jarvis.onboarding.admin_client.dev_signup",
				return_value={"api_key": "k", "api_secret": "s", "agent_url": "ws://h:1", "agent_token": "t"},
			):
				onboarding.dev_onboard("e3@x.com", "Co", "Annual Plan")
			s = frappe.get_single("Jarvis Settings")
			self.assertEqual(s.jarvis_admin_url, "http://other-admin.local")
		finally:
			frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "")
			frappe.db.commit()

	def test_start_signup_throws_when_admin_url_blank(self):
		"""start_signup gets the same pre-flight guard as dev_onboard - admin
		URL must be set deliberately before any signup attempt."""
		_set_token("")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "")
		frappe.db.commit()
		with (
			patch.dict(frappe.local.conf, {"jarvis_admin_url": ""}),
			patch("jarvis.onboarding.admin_client.signup") as mock_signup,
		):
			with self.assertRaises(frappe.ValidationError):
				onboarding.start_signup("e4@x.com", "Co", "Annual Plan")
			mock_signup.assert_not_called()

	def test_start_signup_rejects_plaintext_site_url_in_production(self):
		"""Production onboarding (sandbox_mode off) must hand the admin an
		https:// frappe_site_url - a plaintext http bench fails fast with an
		actionable error, before any admin call."""
		_set_token("")
		frappe.db.set_value(
			"Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "https://admin.example.com"
		)
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", 0)
		frappe.db.commit()
		with (
			patch("frappe.utils.get_url", return_value="http://erp.example.com"),
			patch("jarvis.onboarding.admin_client.signup") as mock_signup,
		):
			with self.assertRaises(frappe.ValidationError):
				onboarding.start_signup("e6@x.com", "Co", "Annual Plan")
			mock_signup.assert_not_called()

	def test_start_signup_allows_https_site_url_in_production(self):
		_set_token("")
		frappe.db.set_value(
			"Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "https://admin.example.com"
		)
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", 0)
		frappe.db.commit()
		with (
			patch("frappe.utils.get_url", return_value="https://erp.example.com"),
			patch("jarvis.onboarding.admin_client.signup", return_value={}) as mock_signup,
		):
			onboarding.start_signup("e7@x.com", "Co", "Annual Plan")
			mock_signup.assert_called_once()

	def test_start_signup_allows_plaintext_site_url_in_sandbox(self):
		"""Sandbox Mode (Jarvis Settings -> Developer) opts a dev/LAN bench
		out of the https requirement."""
		_set_token("")
		frappe.db.set_value(
			"Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "https://admin.example.com"
		)
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", 1)
		frappe.db.commit()
		with (
			patch("frappe.utils.get_url", return_value="http://erp.local:8002"),
			patch("jarvis.onboarding.admin_client.signup", return_value={}) as mock_signup,
		):
			onboarding.start_signup("e8@x.com", "Co", "Annual Plan")
			mock_signup.assert_called_once()

	def test_write_connection_ignores_legacy_api_token(self):
		"""If admin returns the old api_token key, write_connection should NOT
		write it (no accidental cross-population - that field is gone now)."""
		_set_token("")
		onboarding.write_connection({"api_token": "legacy", "agent_url": "ws://h:1"})
		s = frappe.get_single("Jarvis Settings")
		stored = s.get_password("jarvis_admin_api_key", raise_exception=False) or ""
		self.assertEqual(stored, "")

	def test_save_llm_creds_writes_settings_and_fires_save(self):
		"""Step 4 of onboarding: provider/model/api_key land in Jarvis Settings
		and the save triggers the push pipeline (post-unification 2026-05-29:
		always via admin; admin call mocked here, may AdminAuthError if no
		api_key on settings - both paths set last_sync_status)."""
		_set_token("")
		with patch(
			"jarvis.admin_client.post_update_llm_creds", return_value={"action": "restart", "result": "ok"}
		):
			out = onboarding.save_llm_creds(
				provider="Anthropic",
				model="claude-sonnet-4-6",
				api_key="sk-test",
				base_url="https://api.anthropic.com",
			)
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.llm_provider, "Anthropic")
		self.assertEqual(s.llm_model, "claude-sonnet-4-6")
		self.assertEqual(s.get_password("llm_api_key"), "sk-test")
		self.assertEqual(s.llm_base_url, "https://api.anthropic.com")
		self.assertIn("last_sync_status", out)

	def test_save_llm_creds_rejects_missing_required_fields(self):
		with self.assertRaises(frappe.ValidationError):
			onboarding.save_llm_creds(provider="", model="m", api_key="k")
		with self.assertRaises(frappe.ValidationError):
			onboarding.save_llm_creds(provider="Anthropic", model="", api_key="k")
		with self.assertRaises(frappe.ValidationError):
			onboarding.save_llm_creds(provider="Anthropic", model="m", api_key="")

	def test_save_llm_creds_oauth_mode_allows_empty_api_key(self):
		"""REV-1: auth_mode=oauth doesn't require api_key - credentials live in
		the container's auth-profiles.json (pushed separately)."""
		_set_token("")
		with patch(
			"jarvis.admin_client.post_update_llm_creds", return_value={"action": "restart", "result": "ok"}
		):
			out = onboarding.save_llm_creds(
				provider="OpenAI",
				model="gpt-4o",
				api_key="",
				base_url="",
				auth_mode="oauth",
			)
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.llm_auth_mode, "oauth")
		self.assertEqual(s.llm_provider, "OpenAI")
		self.assertEqual(s.llm_model, "gpt-4o")
		self.assertIn("last_sync_status", out)

	def test_save_llm_creds_rejects_unknown_auth_mode(self):
		with self.assertRaises(frappe.ValidationError):
			onboarding.save_llm_creds(provider="OpenAI", model="gpt-4o", api_key="", auth_mode="token")


class TestSignupEmailVerification(FrappeTestCase):
	"""Customer-bench half of the Sprint-1 punch-list email-verification
	work. Pairs with the admin-side flag on
	Jarvis Admin Settings.require_email_verification.

	Bench-side surfaces:
	  start_signup persists api_key + api_secret regardless of which
	    response shape it got, so the poll endpoint can authenticate.
	  check_signup_payment_state wraps admin's get_signup_payment_state.
	"""

	def setUp(self):
		self._snap = _snapshot_settings()
		# Both paths need a non-empty admin URL to pass the pre-flight
		# guard at start_signup; tests don't actually hit it because
		# admin_client.signup is mocked.
		frappe.db.set_value(
			"Jarvis Settings",
			"Jarvis Settings",
			"jarvis_admin_url",
			"https://admin.example.com",
		)
		frappe.db.commit()
		# The https pre-flight guard (production signup requires an https
		# site URL) would trip on the test bench's plain-http URL; stub
		# get_url so these tests stay focused on response persistence. The
		# guard has its own coverage in TestOnboardingSync.
		self._get_url_patch = patch("frappe.utils.get_url", return_value="https://erp.example.com")
		self._get_url_patch.start()

	def tearDown(self):
		self._get_url_patch.stop()
		_restore_settings(self._snap)

	def test_start_signup_persists_api_key_secret_on_verification_response(self):
		# When admin returns pending_verification=True with api_key+secret,
		# the bench MUST store both so the subsequent poll endpoint can
		# authenticate during the verification window. Without this, the
		# wizard would call check_signup_payment_state with no creds and
		# admin would 401.
		with patch(
			"jarvis.onboarding.admin_client.signup",
			return_value={
				"ok": True,
				"api_key": "verify-key",
				"api_secret": "verify-secret",
				"customer": "alice@example.com",
				"pending_verification": True,
			},
		):
			out = onboarding.start_signup(
				"verify-test@example.com",
				"Acme",
				"Annual Plan",
			)
		self.assertTrue(out["pending_verification"])
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(
			s.get_password("jarvis_admin_api_key", raise_exception=False),
			"verify-key",
		)
		self.assertEqual(
			s.get_password("jarvis_admin_api_secret", raise_exception=False),
			"verify-secret",
		)
		# The customer email (OAuth grant username) is persisted now; the
		# password is deliberately absent on the verify-on response (admin
		# defers it to the verified poll).
		self.assertEqual(s.get("jarvis_admin_customer_email"), "alice@example.com")
		self.assertFalse(s.get_password("jarvis_admin_customer_password", raise_exception=False) or "")

	def test_start_signup_legacy_response_still_persists_key_secret(self):
		# Regression pin: the flag-off (legacy) response shape must keep
		# persisting api_key + api_secret on the bench - all subsequent
		# admin calls (finish_payment, get_connection, sync_connection,
		# rotate-secret, push_oauth_blob) authenticate via these.
		with patch(
			"jarvis.onboarding.admin_client.signup",
			return_value={
				"ok": True,
				"api_key": "legacy-key",
				"api_secret": "legacy-secret",
				"customer": "bob@example.com",
				"customer_password": "bob-pw",
				"razorpay_key_id": "rzp_test_X",
				"razorpay_order_id": "order_LEGACY",
				"amount_inr": 12000,
			},
		):
			out = onboarding.start_signup(
				"legacy-test@example.com",
				"Bob Inc",
				"Annual Plan",
			)
		self.assertEqual(out["razorpay_order_id"], "order_LEGACY")
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(
			s.get_password("jarvis_admin_api_key", raise_exception=False),
			"legacy-key",
		)
		# Flag-off path carries the OAuth password in the signup response; the
		# bench persists it (+ the email) for bearer auth on subsequent calls.
		self.assertEqual(s.get("jarvis_admin_customer_email"), "bob@example.com")
		self.assertEqual(
			s.get_password("jarvis_admin_customer_password", raise_exception=False),
			"bob-pw",
		)

	def test_check_signup_payment_state_returns_pending(self):
		# Customer hasn't clicked the link yet - admin returns
		# pending_verification: True. Wizard keeps showing the "check
		# your email" screen.
		with patch(
			"jarvis.onboarding.admin_client.get_signup_payment_state",
			return_value={"pending_verification": True},
		):
			out = onboarding.check_signup_payment_state()
		self.assertTrue(out["pending_verification"])

	def test_check_signup_payment_state_returns_razorpay_payload(self):
		# Customer clicked the link - admin returns the deferred order
		# details. Wizard transitions to Razorpay Checkout.
		with patch(
			"jarvis.onboarding.admin_client.get_signup_payment_state",
			return_value={
				"pending_verification": False,
				"razorpay_order_id": "order_VERIFIED",
				"razorpay_key_id": "rzp_test_X",
				"amount_inr": 12000,
			},
		):
			out = onboarding.check_signup_payment_state()
		self.assertFalse(out["pending_verification"])
		self.assertEqual(out["razorpay_order_id"], "order_VERIFIED")

	def test_check_signup_payment_state_persists_customer_password(self):
		# On the verified poll admin delivers the OAuth password once. The
		# bench must persist it so later admin calls use bearer auth.
		with patch(
			"jarvis.onboarding.admin_client.get_signup_payment_state",
			return_value={
				"pending_verification": False,
				"razorpay_order_id": "order_VERIFIED",
				"razorpay_key_id": "rzp_test_X",
				"amount_inr": 12000,
				"customer_password": "verified-pw",
			},
		):
			out = onboarding.check_signup_payment_state()
		self.assertFalse(out["pending_verification"])
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(
			s.get_password("jarvis_admin_customer_password", raise_exception=False),
			"verified-pw",
		)

	def test_check_signup_payment_state_requires_admin_url(self):
		# Same pre-flight guard as start_signup - misconfigured bench
		# shouldn't silently route to DEFAULT_ADMIN_URL.
		frappe.db.set_value(
			"Jarvis Settings",
			"Jarvis Settings",
			"jarvis_admin_url",
			"",
		)
		frappe.db.commit()
		with (
			patch.dict(frappe.local.conf, {"jarvis_admin_url": ""}),
			patch(
				"jarvis.onboarding.admin_client.get_signup_payment_state",
			) as mock_call,
		):
			with self.assertRaises(frappe.ValidationError):
				onboarding.check_signup_payment_state()
			mock_call.assert_not_called()


class TestGetLlmSyncStatus(FrappeTestCase):
	"""The polling endpoint that the onboarding + account pages hit while
	the background admin sync is running."""

	def setUp(self):
		self._snap = _snapshot_settings()
		_set_token("admin-key")

	def tearDown(self):
		_restore_settings(self._snap)

	def test_returns_pending_true_when_status_starts_with_pending(self):
		s = frappe.get_single("Jarvis Settings")
		s.db_set("last_sync_status", "pending: provisioning container", update_modified=False)
		frappe.db.commit()
		out = onboarding.get_llm_sync_status()
		self.assertEqual(out["last_sync_status"], "pending: provisioning container")
		self.assertTrue(out["pending"])

	def test_returns_pending_false_for_ok_status(self):
		s = frappe.get_single("Jarvis Settings")
		s.db_set("last_sync_status", "ok (restart via admin)", update_modified=False)
		frappe.db.commit()
		out = onboarding.get_llm_sync_status()
		self.assertFalse(out["pending"])

	def test_returns_pending_false_for_failed_status(self):
		s = frappe.get_single("Jarvis Settings")
		s.db_set("last_sync_status", "failed: admin unreachable: boom", update_modified=False)
		frappe.db.commit()
		out = onboarding.get_llm_sync_status()
		self.assertFalse(out["pending"])

	def test_shape_has_expected_keys(self):
		out = onboarding.get_llm_sync_status()
		self.assertIn("last_sync_at", out)
		self.assertIn("last_sync_status", out)
		self.assertIn("pending", out)
		self.assertIn("subscription_status", out)
		self.assertIn("warnings", out)
		self.assertIn("model_statuses", out)

	# -- Apply-warning propagation (subscription_status + warnings) -------

	def test_returns_parsed_warnings_and_subscription_status(self):
		"""The pool sync worker stores warnings as a JSON array string;
		get_llm_sync_status must hand back a parsed list of dicts, plus
		the raw subscription_status string, to the SPA poller."""
		s = frappe.get_single("Jarvis Settings")
		s.db_set("last_subscription_status", "unverified", update_modified=False)
		s.db_set(
			"last_sync_warnings",
			'[{"code": "subscription_unverified", "message": "probe failed"}]',
			update_modified=False,
		)
		frappe.db.commit()
		out = onboarding.get_llm_sync_status()
		self.assertEqual(out["subscription_status"], "unverified")
		self.assertEqual(
			out["warnings"],
			[{"code": "subscription_unverified", "message": "probe failed"}],
		)

	def test_empty_warnings_and_subscription_status_default_cleanly(self):
		"""No pool sync has run yet (or the fleet is on a pre-warnings
		contract) - both fields are empty and must degrade to "" / []
		rather than raise."""
		s = frappe.get_single("Jarvis Settings")
		s.db_set("last_subscription_status", "", update_modified=False)
		s.db_set("last_sync_warnings", "", update_modified=False)
		frappe.db.commit()
		out = onboarding.get_llm_sync_status()
		self.assertEqual(out["subscription_status"], "")
		self.assertEqual(out["warnings"], [])

	def test_corrupt_warnings_json_degrades_to_empty_list(self):
		"""A malformed last_sync_warnings value must never 500 this poller -
		it must degrade to an empty list."""
		s = frappe.get_single("Jarvis Settings")
		s.db_set("last_sync_warnings", "{not valid json", update_modified=False)
		frappe.db.commit()
		out = onboarding.get_llm_sync_status()
		self.assertEqual(out["warnings"], [])

	def test_non_list_warnings_json_degrades_to_empty_list(self):
		"""Valid JSON that isn't a list (e.g. a stray object) must also
		degrade to [] - the SPA always expects a list of {code, message}."""
		s = frappe.get_single("Jarvis Settings")
		s.db_set("last_sync_warnings", '{"code": "x", "message": "y"}', update_modified=False)
		frappe.db.commit()
		out = onboarding.get_llm_sync_status()
		self.assertEqual(out["warnings"], [])

	# -- Per-model verdicts (model_statuses, contract 1.11) --------------

	def test_returns_parsed_model_statuses(self):
		"""The pool sync worker stores the fleet's per-model verdicts as a JSON
		array string; get_llm_sync_status must hand back a parsed list of dicts
		so the AI-models list can key each api-key row's health off it."""
		s = frappe.get_single("Jarvis Settings")
		s.db_set(
			"last_model_statuses",
			'[{"provider": "openai_compat", "model": "claude-sonnet-4-6", "status": "failed"}]',
			update_modified=False,
		)
		frappe.db.commit()
		out = onboarding.get_llm_sync_status()
		self.assertEqual(
			out["model_statuses"],
			[{"provider": "openai_compat", "model": "claude-sonnet-4-6", "status": "failed"}],
		)

	def test_empty_model_statuses_defaults_to_empty_list(self):
		"""No pool sync yet, or a pre-1.11 fleet - the field is empty and must
		degrade to [] rather than raise."""
		s = frappe.get_single("Jarvis Settings")
		s.db_set("last_model_statuses", "", update_modified=False)
		frappe.db.commit()
		self.assertEqual(onboarding.get_llm_sync_status()["model_statuses"], [])

	def test_corrupt_or_non_list_model_statuses_degrades_to_empty_list(self):
		"""A malformed or non-list last_model_statuses must never 500 this poller."""
		s = frappe.get_single("Jarvis Settings")
		for bad in ("{not valid json", '{"model": "m", "status": "failed"}'):
			s.db_set("last_model_statuses", bad, update_modified=False)
			frappe.db.commit()
			self.assertEqual(onboarding.get_llm_sync_status()["model_statuses"], [])


class TestApplyDevConnection(FrappeTestCase):
	"""jarvis.onboarding.apply_dev_connection - the bench-only companion that
	finishes the operator dev-signup flow. Admin v2 un-whitelisted
	dev_force_signup (closed the free-container backdoor), so the browser can no
	longer POST it as guest; an operator runs dev_force_signup on the admin bench
	via `bench execute` and applies its JSON here."""

	# The full key set admin's dev_force_signup returns.
	_DEV_DATA = {
		"customer": "dev@example.com",
		"api_key": "dev-key",
		"api_secret": "dev-secret",
		"customer_password": "dev-pw",
		"agent_url": "ws://localhost:19003",
		"agent_token": "dev-agent-token",
		"tenant": "T-DEV-1",
		"subscription": "Annual Plan",
		"tenant_status": "running",
	}

	def setUp(self):
		self._snap = _snapshot_settings()
		self._orig_sandbox = frappe.db.get_single_value("Jarvis Settings", "sandbox_mode")
		_set_token("")

	def tearDown(self):
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", self._orig_sandbox or 0)
		frappe.db.commit()
		_restore_settings(self._snap)

	def _sandbox(self, on: bool):
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", 1 if on else 0)
		frappe.db.commit()

	def test_happy_path_writes_connection_and_returns_readiness(self):
		"""Sandbox on + a valid dict: the native creds + container connection are
		persisted, and the return is is_ready_for_chat()'s {ready, reason} shape."""
		self._sandbox(True)
		out = onboarding.apply_dev_connection(dict(self._DEV_DATA))
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.get_password("jarvis_admin_api_key"), "dev-key")
		self.assertEqual(s.get_password("jarvis_admin_api_secret"), "dev-secret")
		self.assertEqual(s.agent_url, "ws://localhost:19003")
		self.assertEqual(s.get_password("agent_token"), "dev-agent-token")
		self.assertEqual(s.get("jarvis_admin_customer_email"), "dev@example.com")
		self.assertIsInstance(out, dict)
		self.assertIn("ready", out)
		self.assertIn("reason", out)

	def test_accepts_json_string_data(self):
		"""A double-encoded string (data handed in as JSON text) is parsed too."""
		import json

		self._sandbox(True)
		onboarding.apply_dev_connection(json.dumps(self._DEV_DATA))
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.get_password("jarvis_admin_api_key"), "dev-key")

	def test_rejects_when_sandbox_off(self):
		"""Same gate as dev_onboard: refuse unless sandbox mode is on, and write
		nothing (never inject an admin connection onto a production bench)."""
		self._sandbox(False)
		with self.assertRaises(frappe.ValidationError):
			onboarding.apply_dev_connection(dict(self._DEV_DATA))
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.get_password("jarvis_admin_api_key", raise_exception=False) or "", "")

	def test_rejects_malformed_dicts(self):
		"""Non-dict input and a dict missing the required credential keys both
		fail fast with a ValidationError and persist nothing."""
		self._sandbox(True)
		with self.assertRaises(frappe.ValidationError):
			onboarding.apply_dev_connection(["not", "a", "dict"])
		with self.assertRaises(frappe.ValidationError):
			onboarding.apply_dev_connection({"agent_url": "ws://h:1"})
		with self.assertRaises(frappe.ValidationError):
			onboarding.apply_dev_connection({"api_key": "k"})  # missing api_secret
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.get_password("jarvis_admin_api_key", raise_exception=False) or "", "")


class TestDevOnboardAdminBlocked(FrappeTestCase):
	"""When admin has un-whitelisted dev_force_signup, dev_onboard must surface
	the operator bench flow, NOT the misleading 'check admin credentials' toast,
	and must not persist a half-written connection."""

	def setUp(self):
		self._snap = _snapshot_settings()
		self._orig_sandbox = frappe.db.get_single_value("Jarvis Settings", "sandbox_mode")
		_set_token("")
		frappe.db.set_value(
			"Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "http://admin.example.com"
		)
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", 1)
		frappe.db.commit()

	def tearDown(self):
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", self._orig_sandbox or 0)
		frappe.db.commit()
		_restore_settings(self._snap)

	def test_surfaces_operator_flow_when_not_whitelisted(self):
		"""The "... is not whitelisted" refusal (whichever admin exception carries
		it) is intercepted: the message names apply_dev_connection and NOT the
		credential toast, and no connection is written."""
		from jarvis.exceptions import AdminAuthError

		with patch(
			"jarvis.onboarding.admin_client.dev_signup",
			side_effect=AdminAuthError("dev_force_signup is not whitelisted.", status_code=403),
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				onboarding.dev_onboard("e@x.com", "Co", "Annual Plan")
		msg = str(ctx.exception)
		self.assertIn("apply_dev_connection", msg)
		self.assertNotIn("check the bench's admin credentials", msg)
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.get_password("jarvis_admin_api_key", raise_exception=False) or "", "")

	def test_other_admin_errors_keep_their_clean_toast(self):
		"""Regression guard: a NON-block admin failure must NOT be swallowed into
		the operator-flow message; it keeps its own clean toast."""
		from jarvis.exceptions import AdminUnreachableError

		with patch(
			"jarvis.onboarding.admin_client.dev_signup",
			side_effect=AdminUnreachableError("boom"),
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				onboarding.dev_onboard("e@x.com", "Co", "Annual Plan")
		msg = str(ctx.exception)
		self.assertIn("unreachable", msg)
		self.assertNotIn("apply_dev_connection", msg)

	def test_admin_v1_that_still_whitelists_succeeds(self):
		"""Backwards compat: an older admin v1 that still whitelists
		dev_force_signup returns a connection normally; dev_onboard persists it
		(no interception)."""
		with patch(
			"jarvis.onboarding.admin_client.dev_signup",
			return_value={
				"customer": "v1@x.com",
				"api_key": "v1-key",
				"api_secret": "v1-secret",
				"agent_url": "ws://localhost:19009",
				"agent_token": "v1-tok",
			},
		):
			onboarding.dev_onboard("e@x.com", "Co", "Annual Plan")
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.get_password("jarvis_admin_api_key"), "v1-key")
		self.assertEqual(s.agent_url, "ws://localhost:19009")
