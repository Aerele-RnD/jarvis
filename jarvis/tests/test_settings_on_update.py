"""Tests for Jarvis Settings on_update classification + push behaviour.

`Jarvis Settings` is a Single — there's exactly one row in the whole DB,
shared by tests, the live UI, and bench commands like
``openclaw_bootstrap``. To make these tests deterministic we have to
clobber that singleton with known values; but if we leave it clobbered,
every run of ``bench run-tests --app jarvis`` would silently wipe the
user's real openclaw + LLM credentials.

`_SettingsSingletonTestCase` snapshots the pre-test field values in
``setUpClass`` and restores them in ``tearDownClass`` so the suite leaves
no footprint on the singleton. Password fields are read via
``get_password()`` (which returns the real cleartext) instead of
``settings.get()`` (which returns ``*****``) so the restore actually puts
the credentials back.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import OpenclawReloadFailedError, OpenclawUnreachableError


# Field defaults that mark operator config as "complete"
OPERATOR_COMPLETE = {
    "agent_url": "ws://127.0.0.1:18789",
    "agent_token": "test-token-abc",
    "agent_llm_key_path": "/tmp/jarvis-test/llm.key",
    "agent_config_path": "/tmp/jarvis-test/openclaw.json",
    "agent_compose_dir": "/tmp/jarvis-test/openclaw",
}

LLM_BASELINE = {
    "llm_provider": "Moonshot (Kimi)",
    "llm_model": "kimi-k2.6",
    "llm_api_key": "sk-original-1234",
    "llm_base_url": "",
}

# Plain-text fields the tests overwrite. Snapshotted via settings.get(...).
_SNAPSHOT_PLAIN_FIELDS = (
    "agent_url",
    "agent_llm_key_path",
    "agent_config_path",
    "agent_compose_dir",
    "llm_provider",
    "llm_model",
    "llm_base_url",
    "llm_auth_mode",
    "llm_oauth_account_email",
    "llm_oauth_connected_at",
    "llm_oauth_last_refresh_at",
    "llm_oauth_access_token_expires_at",
    "last_sync_status",
    "last_sync_at",
)

# Password fields the tests overwrite. Snapshotted via get_password() because
# settings.get(field) returns the masked "*****" string for these.
_SNAPSHOT_PASSWORD_FIELDS = (
    "agent_token",
    "llm_api_key",
    "jarvis_admin_api_key",
    "llm_oauth_refresh_token",
    "llm_oauth_access_token",
)


def _reset_settings():
    settings = frappe.get_single("Jarvis Settings")
    # Use db_set to set up state without triggering on_update.
    # jarvis_admin_url/_api_key cleared so the default fixture exercises the
    # local-openclaw (dev) branch; the admin-branch test sets the key itself.
    base = {**OPERATOR_COMPLETE, **LLM_BASELINE,
            "jarvis_admin_url": "", "jarvis_admin_api_key": "",
            "last_sync_status": "", "last_sync_at": None}
    for field, value in base.items():
        settings.db_set(field, value)
    frappe.db.commit()


class _SettingsSingletonTestCase(FrappeTestCase):
    """Base class for tests that mutate the Jarvis Settings singleton.

    Snapshots the singleton's pre-test state in setUpClass and restores
    it in tearDownClass so running the suite leaves no footprint on the
    user's real openclaw / LLM credentials.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        settings = frappe.get_single("Jarvis Settings")
        snapshot: dict[str, object] = {
            f: settings.get(f) for f in _SNAPSHOT_PLAIN_FIELDS
        }
        for f in _SNAPSHOT_PASSWORD_FIELDS:
            # get_password returns None for unset/cleared Password fields
            # (with raise_exception=False); db_set later treats "" the same
            # as None for our purposes.
            snapshot[f] = settings.get_password(f, raise_exception=False) or ""
        cls._jarvis_settings_snapshot = snapshot

    @classmethod
    def tearDownClass(cls):
        try:
            settings = frappe.get_single("Jarvis Settings")
            for field, value in cls._jarvis_settings_snapshot.items():
                # db_set bypasses on_update — we don't want to re-fire the
                # credentials push from the snapshot during restoration.
                settings.db_set(field, value)
            frappe.db.commit()
        finally:
            super().tearDownClass()


class TestOnUpdateClassification(_SettingsSingletonTestCase):
    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_no_change_is_noop(self):
        settings = frappe.get_single("Jarvis Settings")
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
             patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
            settings.save()
            self.assertFalse(reload_mock.called)
            self.assertFalse(restart_mock.called)

    def test_only_key_change_triggers_reload(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-new-key-9999"
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
             patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
            settings.save()
            reload_mock.assert_called_once()
            self.assertFalse(restart_mock.called)

    def test_provider_change_triggers_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_provider = "Anthropic"
        settings.llm_model = "claude-sonnet-4-6"
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
             patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
            settings.save()
            self.assertFalse(reload_mock.called)
            restart_mock.assert_called_once()

    def test_model_only_change_triggers_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_model = "kimi-k2.5"
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
             patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
            settings.save()
            self.assertFalse(reload_mock.called)
            restart_mock.assert_called_once()

    def test_base_url_change_triggers_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_base_url = "https://custom.example.com/v1"
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
             patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
            settings.save()
            self.assertFalse(reload_mock.called)
            restart_mock.assert_called_once()

    def test_key_and_provider_change_triggers_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-anthropic-key"
        settings.llm_provider = "Anthropic"
        settings.llm_model = "claude-sonnet-4-6"
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
             patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
            settings.save()
            self.assertFalse(reload_mock.called)
            restart_mock.assert_called_once()

    def test_temperature_change_is_noop(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_temperature = 0.5
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
             patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
            settings.save()
            self.assertFalse(reload_mock.called)
            self.assertFalse(restart_mock.called)

    def test_max_output_tokens_change_is_noop(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_max_output_tokens = 8192
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
             patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
            settings.save()
            self.assertFalse(reload_mock.called)
            self.assertFalse(restart_mock.called)


class TestOnUpdateOperatorGate(_SettingsSingletonTestCase):
    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_missing_gateway_url_skips(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("agent_url", "")
        frappe.db.commit()
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-new"
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock:
            settings.save()
            self.assertFalse(reload_mock.called)
        settings = frappe.get_single("Jarvis Settings")
        self.assertIn("skipped", settings.last_sync_status or "")

    def test_missing_token_skips(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("agent_token", "")
        frappe.db.commit()
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-new"
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock:
            settings.save()
            self.assertFalse(reload_mock.called)

    def test_missing_compose_dir_skips_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("agent_compose_dir", "")
        frappe.db.commit()
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_provider = "Anthropic"
        settings.llm_model = "claude-sonnet-4-6"
        with patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
            settings.save()
            self.assertFalse(restart_mock.called)


class TestOnUpdateAdminBranch(_SettingsSingletonTestCase):
    """The admin-vs-local dispatch keys on the presence of an admin api token
    (set by onboarding), not on jarvis_admin_url (which onboarding never sets)."""

    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_admin_api_key_routes_to_admin_not_local(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("jarvis_admin_api_key", "cust-token-xyz")  # as onboarding sets it
        frappe.db.commit()
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-new"
        # api_key-only change → classifier returns "reload" → _sync_via_admin
        # dispatches to post_rotate_llm_secret (hot-rotate, no container restart).
        # This is a behavior improvement from the prod-wiring work: api-key
        # rotation used to restart the container via post_update_llm_creds; the
        # new unified action-based dispatch routes reload through the rotate
        # endpoint regardless of auth_mode.
        with patch("jarvis.admin_client.post_rotate_llm_secret",
                   return_value={"action": "reload"}) as admin_mock, \
             patch("jarvis.openclaw_push.push_creds_reload") as local_mock:
            settings.save()
        admin_mock.assert_called_once()
        self.assertFalse(local_mock.called)

    def test_no_admin_api_key_routes_to_local(self):
        # _reset_settings cleared the key → local (dev) path.
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-new"
        with patch("jarvis.admin_client.post_rotate_llm_secret") as admin_mock, \
             patch("jarvis.openclaw_push.push_creds_reload") as local_mock:
            settings.save()
        local_mock.assert_called_once()
        self.assertFalse(admin_mock.called)


class TestOnUpdateStatus(_SettingsSingletonTestCase):
    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_records_ok_reload_on_success(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-new"
        with patch("jarvis.openclaw_push.push_creds_reload"):
            settings.save()
        settings = frappe.get_single("Jarvis Settings")
        self.assertEqual(settings.last_sync_status, "ok (reload)")
        self.assertIsNotNone(settings.last_sync_at)

    def test_records_ok_restart_on_success(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_provider = "Anthropic"
        settings.llm_model = "claude-sonnet-4-6"
        with patch("jarvis.openclaw_push.push_creds_restart"):
            settings.save()
        settings = frappe.get_single("Jarvis Settings")
        self.assertEqual(settings.last_sync_status, "ok (restart)")

    def test_records_failure_when_push_raises(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-new"
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock:
            reload_mock.side_effect = OpenclawUnreachableError("connect refused")
            # Save must still succeed even though push fails
            settings.save()
        settings = frappe.get_single("Jarvis Settings")
        self.assertIn("failed", settings.last_sync_status or "")
        self.assertIn("OpenclawUnreachableError", settings.last_sync_status or "")
        # The new key value must still have persisted (Password fields are masked on doc;
        # use get_password() to retrieve the actual stored value)
        self.assertEqual(settings.get_password("llm_api_key"), "sk-new")

    def test_save_succeeds_even_when_push_fails(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-persisted"
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock:
            reload_mock.side_effect = OpenclawReloadFailedError("boom")
            try:
                settings.save()
            except Exception:
                self.fail("save() should not raise when push fails")
        settings = frappe.get_single("Jarvis Settings")
        # Password fields are masked on the doc object; use get_password() to verify persistence
        self.assertEqual(settings.get_password("llm_api_key"), "sk-persisted")


class TestValidateAuthMode(_SettingsSingletonTestCase):
	"""validate() requires the right credential per auth mode."""

	def setUp(self):
		from frappe.utils.password import remove_encrypted_password
		_reset_settings()
		# Properly clear Password fields by deleting them from the __Auth table.
		# db_set() on a Password field leaves the encrypted value behind.
		for f in ("llm_api_key", "llm_oauth_refresh_token", "llm_oauth_access_token"):
			remove_encrypted_password("Jarvis Settings", "Jarvis Settings", f)
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "api_key", update_modified=False)
		frappe.db.commit()

	def test_api_key_mode_requires_api_key(self):
		settings = frappe.get_single("Jarvis Settings")
		settings.llm_auth_mode = "api_key"
		settings.llm_api_key = ""
		settings.llm_provider = "OpenAI"
		settings.llm_model = "gpt-4o-mini"
		with self.assertRaises(frappe.ValidationError):
			settings.validate()

	def test_subscription_mode_requires_refresh_token(self):
		settings = frappe.get_single("Jarvis Settings")
		settings.llm_auth_mode = "subscription"
		settings.llm_oauth_refresh_token = ""
		settings.llm_provider = "OpenAI"
		settings.llm_model = "gpt-4o-mini"
		with self.assertRaises(frappe.ValidationError):
			settings.validate()

	def test_subscription_mode_with_refresh_token_passes(self):
		# Seed via db_set so get_password sees it as set
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_oauth_refresh_token", "RT-xyz", update_modified=False)
		frappe.db.commit()
		settings = frappe.get_single("Jarvis Settings")  # reload
		settings.llm_auth_mode = "subscription"
		settings.llm_provider = "OpenAI"
		settings.llm_model = "gpt-4o-mini"
		# Should not raise
		settings.validate()

	def test_api_key_mode_with_api_key_passes(self):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_api_key", "sk-xyz", update_modified=False)
		frappe.db.commit()
		settings = frappe.get_single("Jarvis Settings")  # reload
		settings.llm_auth_mode = "api_key"
		settings.llm_provider = "OpenAI"
		settings.llm_model = "gpt-4o-mini"
		settings.validate()


class TestClassifyAuthModeSwitch(_SettingsSingletonTestCase):
	"""Mode-switch and OAuth-credential changes route to the right push path."""

	def setUp(self):
		_reset_settings()
		settings = frappe.get_single("Jarvis Settings")
		# Seed an OAuth refresh token via db_set so mode-switch tests can use subscription
		settings.db_set("llm_oauth_refresh_token", "RT-seed", update_modified=False)
		settings.db_set("llm_oauth_access_token", "AT-seed", update_modified=False)
		settings.db_set("llm_auth_mode", "api_key", update_modified=False)
		frappe.db.commit()

	def test_api_key_to_subscription_triggers_restart(self):
		settings = frappe.get_single("Jarvis Settings")
		settings.llm_auth_mode = "subscription"
		with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
		     patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
			settings.save()
			self.assertFalse(reload_mock.called)
			restart_mock.assert_called_once()

	def test_subscription_to_api_key_triggers_restart_and_clears_oauth(self):
		# Start in subscription mode
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "subscription", update_modified=False)
		frappe.db.commit()
		# Switch to api_key
		settings = frappe.get_single("Jarvis Settings")
		settings.llm_auth_mode = "api_key"
		with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
		     patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
			settings.save()
			self.assertFalse(reload_mock.called)
			restart_mock.assert_called_once()
		# OAuth fields cleared
		settings = frappe.get_single("Jarvis Settings")
		self.assertFalse(settings.get_password("llm_oauth_refresh_token", raise_exception=False))
		self.assertFalse(settings.get_password("llm_oauth_access_token", raise_exception=False))

	def test_access_token_rotation_triggers_reload(self):
		# Set up subscription mode with a known access token
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "subscription", update_modified=False)
		frappe.db.commit()
		# Rotate the access token (what the cron will do)
		settings = frappe.get_single("Jarvis Settings")
		settings.llm_oauth_access_token = "AT-rotated"
		with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
		     patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
			settings.save()
			reload_mock.assert_called_once()
			self.assertFalse(restart_mock.called)

	def test_refresh_token_change_triggers_restart(self):
		# Re-authorize: a new refresh token comes in. Structural change.
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "subscription", update_modified=False)
		frappe.db.commit()
		settings = frappe.get_single("Jarvis Settings")
		settings.llm_oauth_refresh_token = "RT-renewed"
		with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock, \
		     patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
			settings.save()
			self.assertFalse(reload_mock.called)
			restart_mock.assert_called_once()


class TestResolveLlmSecretForPush(_SettingsSingletonTestCase):
	"""JarvisSettings._resolve_llm_secret_for_push picks the right Password field."""

	def setUp(self):
		from frappe.utils.password import remove_encrypted_password
		_reset_settings()
		for f in ("llm_api_key", "llm_oauth_access_token"):
			remove_encrypted_password("Jarvis Settings", "Jarvis Settings", f)
			frappe.db.set_single_value("Jarvis Settings", f, None)
		frappe.db.commit()

	def test_api_key_mode_returns_api_key(self):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "api_key", update_modified=False)
		settings.db_set("llm_api_key", "sk-1", update_modified=False)
		frappe.db.commit()
		settings.reload()
		self.assertEqual(settings._resolve_llm_secret_for_push(), "sk-1")

	def test_subscription_mode_returns_access_token(self):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "subscription", update_modified=False)
		settings.db_set("llm_oauth_access_token", "AT-1", update_modified=False)
		frappe.db.commit()
		settings.reload()
		self.assertEqual(settings._resolve_llm_secret_for_push(), "AT-1")

	def test_subscription_mode_empty_token_returns_empty(self):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "subscription", update_modified=False)
		frappe.db.commit()
		settings.reload()
		self.assertEqual(settings._resolve_llm_secret_for_push(), "")


class TestSyncViaAdminModeAware(_SettingsSingletonTestCase):
	"""_sync_via_admin dispatches to the right admin endpoint per action + mode."""

	def setUp(self):
		from frappe.utils.password import remove_encrypted_password
		_reset_settings()
		for f in ("llm_api_key", "llm_oauth_access_token", "llm_oauth_refresh_token"):
			remove_encrypted_password("Jarvis Settings", "Jarvis Settings", f)
			frappe.db.set_single_value("Jarvis Settings", f, None)
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("jarvis_admin_api_key", "test-admin-key", update_modified=False)
		settings.db_set("jarvis_admin_api_secret", "test-admin-secret", update_modified=False)
		frappe.db.commit()

	@patch("jarvis.admin_client.post_rotate_llm_secret")
	@patch("jarvis.admin_client.post_update_llm_creds")
	def test_reload_action_calls_rotate_llm_secret(self, mock_update, mock_rotate):
		mock_rotate.return_value = {"action": "reload"}
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "subscription", update_modified=False)
		settings.db_set("llm_oauth_access_token", "AT-1", update_modified=False)
		frappe.db.commit()
		settings.reload()
		settings._sync_via_admin("reload")
		mock_rotate.assert_called_once_with(secret="AT-1")
		mock_update.assert_not_called()

	@patch("jarvis.admin_client.post_rotate_llm_secret")
	@patch("jarvis.admin_client.post_update_llm_creds")
	def test_restart_subscription_calls_update_with_auth_mode(self, mock_update, mock_rotate):
		mock_update.return_value = {"action": "restart"}
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "subscription", update_modified=False)
		settings.db_set("llm_oauth_access_token", "AT-1", update_modified=False)
		settings.db_set("llm_provider", "OpenAI", update_modified=False)
		frappe.db.commit()
		settings.reload()
		settings._sync_via_admin("restart")
		mock_update.assert_called_once()
		kw = mock_update.call_args.kwargs
		self.assertEqual(kw["auth_mode"], "subscription")
		self.assertEqual(kw["api_key"], "AT-1")
		mock_rotate.assert_not_called()

	@patch("jarvis.admin_client.post_rotate_llm_secret")
	@patch("jarvis.admin_client.post_update_llm_creds")
	def test_restart_api_key_calls_update_with_api_key_mode(self, mock_update, mock_rotate):
		mock_update.return_value = {"action": "restart"}
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "api_key", update_modified=False)
		settings.db_set("llm_api_key", "sk-1", update_modified=False)
		settings.db_set("llm_provider", "OpenAI", update_modified=False)
		frappe.db.commit()
		settings.reload()
		settings._sync_via_admin("restart")
		kw = mock_update.call_args.kwargs
		self.assertEqual(kw["auth_mode"], "api_key")
		self.assertEqual(kw["api_key"], "sk-1")

	@patch("jarvis.admin_client.post_rotate_llm_secret")
	def test_rate_limited_is_logged_not_raised(self, mock_rotate):
		from jarvis.exceptions import AdminRateLimitedError
		mock_rotate.side_effect = AdminRateLimitedError(retry_after_seconds=600)
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("llm_auth_mode", "subscription", update_modified=False)
		settings.db_set("llm_oauth_access_token", "AT-1", update_modified=False)
		before_status = settings.last_sync_status
		# Should not raise
		settings._sync_via_admin("reload")
		# last_sync_status unchanged (rate-limit is a bench-side bug, not a creds problem)
		settings.reload()
		self.assertEqual(settings.last_sync_status, before_status)
