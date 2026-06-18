"""Tests for jarvis.onboarding sync + wrappers (admin_client mocked)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import onboarding


def _set_token(value, secret="secret"):
	"""Set both native credentials for tests that exercise the authenticated
	admin path. value="" clears them (simulates 'not onboarded')."""
	s = frappe.get_single("Jarvis Settings")
	s.db_set("jarvis_admin_api_key", value)
	s.db_set("jarvis_admin_api_secret", secret if value else "")
	s.db_set("agent_url", "")
	frappe.db.commit()


# Fields these tests write to. Snapshot in setUp, restore in tearDown so
# tests run against a real site (e.g. jarvis.localhost) don't clobber the
# operator's actual onboarded state - Frappe Singles aren't transactionally
# rolled back between tests.
_SNAPSHOTTED_FIELDS = (
	"jarvis_admin_url", "jarvis_admin_api_key", "jarvis_admin_api_secret",
	"agent_url", "agent_token",
)


def _snapshot_settings() -> dict:
	s = frappe.get_single("Jarvis Settings")
	snap = {}
	for f in _SNAPSHOTTED_FIELDS:
		# Password fields → get_password; plain → attribute. Both safe.
		v = s.get_password(f, raise_exception=False) if f.endswith(("_key", "_secret", "_token")) else s.get(f)
		snap[f] = v or ""
	return snap


def _restore_settings(snap: dict) -> None:
	for f, v in snap.items():
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", f, v)
	frappe.db.commit()


class TestSyncConnection(FrappeTestCase):
	def setUp(self):
		self._snap = _snapshot_settings()

	def tearDown(self):
		_restore_settings(self._snap)

	def test_sync_writes_connection_when_assigned(self):
		_set_token("tok")
		with patch("jarvis.onboarding.admin_client.get_connection",
				   return_value={"agent_url": "ws://localhost:19000", "agent_token": "k", "tenant_status": "running"}):
			out = onboarding.sync_connection()
		self.assertTrue(out["synced"])
		self.assertEqual(frappe.get_single("Jarvis Settings").agent_url, "ws://localhost:19000")

	def test_sync_noop_when_pending(self):
		_set_token("tok")
		with patch("jarvis.onboarding.admin_client.get_connection",
				   return_value={"agent_url": "", "tenant_status": "pending"}):
			out = onboarding.sync_connection()
		self.assertFalse(out["synced"])

	def test_sync_skips_when_not_onboarded(self):
		import frappe.model.document
		with patch.object(frappe.model.document.Document, "get_password", return_value=""), \
			 patch("jarvis.onboarding.admin_client.get_connection",
				   side_effect=AssertionError("admin must not be called when not onboarded")):
			out = onboarding.sync_connection()
		self.assertFalse(out["synced"])
		self.assertEqual(out["reason"], "not onboarded")

	def test_dev_onboard_writes_native_credentials_and_connection(self):
		_set_token("")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings",
							"jarvis_admin_url", "http://admin.example.com")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", 1)
		frappe.db.commit()
		with patch("jarvis.onboarding.admin_client.dev_signup",
				   return_value={"customer": "C1", "api_key": "k2", "api_secret": "s2",
								 "agent_url": "ws://localhost:19002", "agent_token": "tok"}):
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
		with patch("jarvis.onboarding.admin_client.dev_signup") as mock_signup:
			with self.assertRaises(frappe.ValidationError):
				onboarding.dev_onboard("e2@x.com", "Co", "Annual Plan")
			mock_signup.assert_not_called()

	def test_dev_onboard_preserves_existing_admin_url(self):
		"""Pre-set jarvis_admin_url stays untouched - dev_onboard never
		writes to the field anymore."""
		_set_token("")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings",
							"jarvis_admin_url", "http://other-admin.local")
		frappe.db.set_value("Jarvis Settings", "Jarvis Settings", "sandbox_mode", 1)
		frappe.db.commit()
		try:
			with patch("jarvis.onboarding.admin_client.dev_signup",
					   return_value={"api_key": "k", "api_secret": "s", "agent_url": "ws://h:1", "agent_token": "t"}):
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
		with patch("jarvis.onboarding.admin_client.signup") as mock_signup:
			with self.assertRaises(frappe.ValidationError):
				onboarding.start_signup("e4@x.com", "Co", "Annual Plan")
			mock_signup.assert_not_called()

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
		with patch("jarvis.admin_client.post_update_llm_creds",
				   return_value={"action": "restart", "result": "ok"}):
			out = onboarding.save_llm_creds(
				provider="Anthropic", model="claude-sonnet-4-6",
				api_key="sk-test", base_url="https://api.anthropic.com",
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
		with patch("jarvis.admin_client.post_update_llm_creds",
				   return_value={"action": "restart", "result": "ok"}):
			out = onboarding.save_llm_creds(
				provider="OpenAI", model="gpt-4o",
				api_key="", base_url="", auth_mode="oauth",
			)
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.llm_auth_mode, "oauth")
		self.assertEqual(s.llm_provider, "OpenAI")
		self.assertEqual(s.llm_model, "gpt-4o")
		self.assertIn("last_sync_status", out)

	def test_save_llm_creds_rejects_unknown_auth_mode(self):
		with self.assertRaises(frappe.ValidationError):
			onboarding.save_llm_creds(provider="OpenAI", model="gpt-4o",
			                          api_key="", auth_mode="token")


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
			"Jarvis Settings", "Jarvis Settings",
			"jarvis_admin_url", "https://admin.example.com",
		)
		frappe.db.commit()

	def tearDown(self):
		_restore_settings(self._snap)

	def test_start_signup_persists_api_key_secret_on_verification_response(self):
		# When admin returns pending_verification=True with api_key+secret,
		# the bench MUST store both so the subsequent poll endpoint can
		# authenticate during the verification window. Without this, the
		# wizard would call check_signup_payment_state with no creds and
		# admin would 401.
		with patch("jarvis.onboarding.admin_client.signup",
		           return_value={
		               "ok": True,
		               "api_key": "verify-key",
		               "api_secret": "verify-secret",
		               "customer": "alice@example.com",
		               "pending_verification": True,
		           }):
			out = onboarding.start_signup(
				"verify-test@example.com", "Acme", "Annual Plan",
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

	def test_start_signup_legacy_response_still_persists_key_secret(self):
		# Regression pin: the flag-off (legacy) response shape must keep
		# persisting api_key + api_secret on the bench - all subsequent
		# admin calls (finish_payment, get_connection, sync_connection,
		# rotate-secret, push_oauth_blob) authenticate via these.
		with patch("jarvis.onboarding.admin_client.signup",
		           return_value={
		               "ok": True,
		               "api_key": "legacy-key",
		               "api_secret": "legacy-secret",
		               "customer": "bob@example.com",
		               "razorpay_key_id": "rzp_test_X",
		               "razorpay_order_id": "order_LEGACY",
		               "amount_inr": 12000,
		           }):
			out = onboarding.start_signup(
				"legacy-test@example.com", "Bob Inc", "Annual Plan",
			)
		self.assertEqual(out["razorpay_order_id"], "order_LEGACY")
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(
			s.get_password("jarvis_admin_api_key", raise_exception=False),
			"legacy-key",
		)

	def test_check_signup_payment_state_returns_pending(self):
		# Customer hasn't clicked the link yet - admin returns
		# pending_verification: True. Wizard keeps showing the "check
		# your email" screen.
		with patch("jarvis.onboarding.admin_client.get_signup_payment_state",
		           return_value={"pending_verification": True}):
			out = onboarding.check_signup_payment_state()
		self.assertTrue(out["pending_verification"])

	def test_check_signup_payment_state_returns_razorpay_payload(self):
		# Customer clicked the link - admin returns the deferred order
		# details. Wizard transitions to Razorpay Checkout.
		with patch("jarvis.onboarding.admin_client.get_signup_payment_state",
		           return_value={
		               "pending_verification": False,
		               "razorpay_order_id": "order_VERIFIED",
		               "razorpay_key_id": "rzp_test_X",
		               "amount_inr": 12000,
		           }):
			out = onboarding.check_signup_payment_state()
		self.assertFalse(out["pending_verification"])
		self.assertEqual(out["razorpay_order_id"], "order_VERIFIED")

	def test_check_signup_payment_state_requires_admin_url(self):
		# Same pre-flight guard as start_signup - misconfigured bench
		# shouldn't silently route to DEFAULT_ADMIN_URL.
		frappe.db.set_value(
			"Jarvis Settings", "Jarvis Settings", "jarvis_admin_url", "",
		)
		frappe.db.commit()
		with patch(
			"jarvis.onboarding.admin_client.get_signup_payment_state",
		) as mock_call:
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
		s.db_set("last_sync_status", "pending: provisioning container",
		         update_modified=False)
		frappe.db.commit()
		out = onboarding.get_llm_sync_status()
		self.assertEqual(out["last_sync_status"], "pending: provisioning container")
		self.assertTrue(out["pending"])

	def test_returns_pending_false_for_ok_status(self):
		s = frappe.get_single("Jarvis Settings")
		s.db_set("last_sync_status", "ok (restart via admin)",
		         update_modified=False)
		frappe.db.commit()
		out = onboarding.get_llm_sync_status()
		self.assertFalse(out["pending"])

	def test_returns_pending_false_for_failed_status(self):
		s = frappe.get_single("Jarvis Settings")
		s.db_set("last_sync_status", "failed: admin unreachable: boom",
		         update_modified=False)
		frappe.db.commit()
		out = onboarding.get_llm_sync_status()
		self.assertFalse(out["pending"])

	def test_shape_has_expected_keys(self):
		out = onboarding.get_llm_sync_status()
		self.assertIn("last_sync_at", out)
		self.assertIn("last_sync_status", out)
		self.assertIn("pending", out)
