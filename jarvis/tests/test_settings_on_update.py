"""Tests for Jarvis Settings on_update classification + admin dispatch.

`Jarvis Settings` is a Single - there's exactly one row in the whole DB,
shared by tests and the live UI. `_SettingsSingletonTestCase` snapshots
the pre-test field values in setUpClass and restores them in
tearDownClass so the suite leaves no footprint on the user's real
credentials.

Post-unification (2026-05-29): on_update always dispatches via
`_sync_via_admin` - there is no longer a bench-local push shortcut. All
tests mock `jarvis.admin_client.*` accordingly.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


LLM_BASELINE = {
    "llm_provider": "Moonshot (Kimi)",
    "llm_model": "kimi-k2.6",
    "llm_api_key": "sk-original-1234",
    "llm_base_url": "",
}

# Plain-text fields the tests overwrite. Snapshotted via settings.get(...).
_SNAPSHOT_PLAIN_FIELDS = (
    "llm_provider",
    "llm_model",
    "llm_base_url",
    "llm_auth_mode",
    "last_sync_status",
    "last_sync_at",
)

# Password fields the tests overwrite. Snapshotted via get_password() because
# settings.get(field) returns the masked "*****" string for these.
_SNAPSHOT_PASSWORD_FIELDS = (
    "llm_api_key",
    "jarvis_admin_api_key",
    "jarvis_admin_api_secret",
)


def _reset_settings():
    """Reset settings to a known baseline. Seeds admin credentials so
    `_sync_via_admin` doesn't fail with `AdminAuthError` (callers mock
    the admin_client HTTP call separately)."""
    settings = frappe.get_single("Jarvis Settings")
    base = {
        **LLM_BASELINE,
        "jarvis_admin_url": "http://127.0.0.1:8000",
        "jarvis_admin_api_key": "test-admin-key",
        "jarvis_admin_api_secret": "test-admin-secret",
        "last_sync_status": "",
        "last_sync_at": None,
    }
    for field, value in base.items():
        settings.db_set(field, value)
    frappe.db.commit()


class _SettingsSingletonTestCase(FrappeTestCase):
    """Snapshots the Jarvis Settings singleton's pre-test state and restores
    it in tearDownClass so running the suite leaves no footprint."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        settings = frappe.get_single("Jarvis Settings")
        snapshot: dict[str, object] = {
            f: settings.get(f) for f in _SNAPSHOT_PLAIN_FIELDS
        }
        for f in _SNAPSHOT_PASSWORD_FIELDS:
            snapshot[f] = settings.get_password(f, raise_exception=False) or ""
        cls._jarvis_settings_snapshot = snapshot

    @classmethod
    def tearDownClass(cls):
        try:
            settings = frappe.get_single("Jarvis Settings")
            for field, value in cls._jarvis_settings_snapshot.items():
                settings.db_set(field, value)
            frappe.db.commit()
        finally:
            super().tearDownClass()


class TestOnUpdateClassification(_SettingsSingletonTestCase):
    """Classifier-output tests. The dispatcher always routes to
    `_sync_via_admin`; we mock that to verify the correct action arg."""

    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_no_change_is_noop(self):
        settings = frappe.get_single("Jarvis Settings")
        with patch.object(type(settings), "_sync_via_admin") as sync_mock:
            settings.save()
        sync_mock.assert_not_called()

    def test_only_key_change_triggers_reload(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-new-key-9999"
        with patch.object(type(settings), "_sync_via_admin") as sync_mock:
            settings.save()
        sync_mock.assert_called_once_with("reload")

    def test_provider_change_triggers_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_provider = "Anthropic"
        settings.llm_model = "claude-sonnet-4-6"
        with patch.object(type(settings), "_sync_via_admin") as sync_mock:
            settings.save()
        sync_mock.assert_called_once_with("restart")

    def test_model_only_change_triggers_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_model = "kimi-k2.5"
        with patch.object(type(settings), "_sync_via_admin") as sync_mock:
            settings.save()
        sync_mock.assert_called_once_with("restart")

    def test_base_url_change_triggers_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_base_url = "https://custom.example.com/v1"
        with patch.object(type(settings), "_sync_via_admin") as sync_mock:
            settings.save()
        sync_mock.assert_called_once_with("restart")

    def test_key_and_provider_change_triggers_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-anthropic-key"
        settings.llm_provider = "Anthropic"
        settings.llm_model = "claude-sonnet-4-6"
        with patch.object(type(settings), "_sync_via_admin") as sync_mock:
            settings.save()
        sync_mock.assert_called_once_with("restart")

    def test_temperature_change_is_noop(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_temperature = 0.5
        with patch.object(type(settings), "_sync_via_admin") as sync_mock:
            settings.save()
        sync_mock.assert_not_called()

    def test_max_output_tokens_change_is_noop(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_max_output_tokens = 8192
        with patch.object(type(settings), "_sync_via_admin") as sync_mock:
            settings.save()
        sync_mock.assert_not_called()


class TestOnUpdateAlwaysAdminPath(_SettingsSingletonTestCase):
    """Unified architecture: on_update always uses `_sync_via_admin`,
    regardless of whether the admin api_key is configured. If admin isn't
    configured, the call fails with AdminAuthError (which we don't mock -
    the test only verifies the path is taken)."""

    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_on_update_routes_to_admin(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-rotated"
        with patch("jarvis.admin_client.post_rotate_llm_secret",
                   return_value={"action": "reload"}) as admin_mock:
            settings.save()
        admin_mock.assert_called_once()


class TestOnUpdateStatus(_SettingsSingletonTestCase):
    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_records_ok_reload_via_admin_on_success(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-new"
        with patch("jarvis.admin_client.post_rotate_llm_secret",
                   return_value={"action": "reload"}):
            settings.save()
        settings = frappe.get_single("Jarvis Settings")
        self.assertEqual(settings.last_sync_status, "ok (reload via admin)")
        self.assertIsNotNone(settings.last_sync_at)

    def test_records_ok_restart_via_admin_on_success(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_provider = "Anthropic"
        settings.llm_model = "claude-sonnet-4-6"
        with patch("jarvis.admin_client.post_update_llm_creds",
                   return_value={"action": "restart"}):
            settings.save()
        settings = frappe.get_single("Jarvis Settings")
        self.assertEqual(settings.last_sync_status, "ok (restart via admin)")

    def test_records_failure_when_admin_unreachable(self):
        from jarvis.exceptions import AdminUnreachableError
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-new"
        with patch("jarvis.admin_client.post_rotate_llm_secret",
                   side_effect=AdminUnreachableError("network is down")):
            settings.save()
        settings = frappe.get_single("Jarvis Settings")
        self.assertIn("failed", settings.last_sync_status or "")
        self.assertIn("admin unreachable", settings.last_sync_status or "")

    def test_save_succeeds_even_when_admin_call_fails(self):
        from jarvis.exceptions import AdminUnreachableError
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-persisted"
        with patch("jarvis.admin_client.post_rotate_llm_secret",
                   side_effect=AdminUnreachableError("boom")):
            try:
                settings.save()
            except Exception:
                self.fail("save() should not raise when admin call fails")
        settings = frappe.get_single("Jarvis Settings")
        # Password field still persisted.
        self.assertEqual(settings.get_password("llm_api_key"), "sk-persisted")


class TestValidateAuthMode(_SettingsSingletonTestCase):
    """validate() requires the right credential per auth mode.

    REV-1: only api_key mode requires a bench-side credential. The
    subscription modes (oauth / legacy subscription) keep credentials on
    the container, so the bench's validate() has no check for them."""

    def setUp(self):
        from frappe.utils.password import remove_encrypted_password
        _reset_settings()
        remove_encrypted_password("Jarvis Settings", "Jarvis Settings", "llm_api_key")
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

    def test_api_key_mode_with_api_key_passes(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("llm_api_key", "sk-xyz", update_modified=False)
        frappe.db.commit()
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_auth_mode = "api_key"
        settings.llm_provider = "OpenAI"
        settings.llm_model = "gpt-4o-mini"
        settings.validate()  # should not raise

    def test_oauth_mode_no_bench_credential_required(self):
        """REV-1: oauth mode credentials live on the container. The bench's
        validate() doesn't require any bench-side credential."""
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_auth_mode = "oauth"
        settings.llm_provider = "OpenAI"
        settings.llm_model = "gpt-4o"
        settings.validate()  # should not raise

    def test_legacy_subscription_mode_no_bench_credential_required(self):
        """Migrated tenants on the legacy 'subscription' value are treated
        the same as oauth - no bench-side credential required."""
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_auth_mode = "subscription"
        settings.llm_provider = "OpenAI"
        settings.llm_model = "gpt-4o"
        settings.validate()  # should not raise


class TestClassifyAuthModeSwitch(_SettingsSingletonTestCase):
    """Mode-switch is structural - always triggers restart."""

    def setUp(self):
        _reset_settings()
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("llm_auth_mode", "api_key", update_modified=False)
        frappe.db.commit()

    def test_api_key_to_oauth_triggers_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_auth_mode = "oauth"
        with patch.object(type(settings), "_sync_via_admin") as sync_mock:
            settings.save()
        sync_mock.assert_called_once_with("restart")

    def test_oauth_to_api_key_triggers_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("llm_auth_mode", "oauth", update_modified=False)
        frappe.db.commit()
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_auth_mode = "api_key"
        with patch.object(type(settings), "_sync_via_admin") as sync_mock:
            settings.save()
        sync_mock.assert_called_once_with("restart")


class TestResolveLlmSecretForPush(_SettingsSingletonTestCase):
    """REV-1: _resolve_llm_secret_for_push returns llm_api_key only.
    Oauth credentials live on the container in auth-profiles.json, not
    in any Jarvis Settings password field."""

    def setUp(self):
        from frappe.utils.password import remove_encrypted_password
        _reset_settings()
        remove_encrypted_password("Jarvis Settings", "Jarvis Settings", "llm_api_key")
        frappe.db.set_single_value("Jarvis Settings", "llm_api_key", None)
        frappe.db.commit()

    def test_api_key_mode_returns_api_key(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("llm_auth_mode", "api_key", update_modified=False)
        settings.db_set("llm_api_key", "sk-1", update_modified=False)
        frappe.db.commit()
        settings.reload()
        self.assertEqual(settings._resolve_llm_secret_for_push(), "sk-1")

    def test_oauth_mode_returns_empty(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("llm_auth_mode", "oauth", update_modified=False)
        frappe.db.commit()
        settings.reload()
        self.assertEqual(settings._resolve_llm_secret_for_push(), "")


class TestSyncViaAdminDispatch(_SettingsSingletonTestCase):
    """_sync_via_admin dispatches to the right admin endpoint per action."""

    def setUp(self):
        _reset_settings()

    @patch("jarvis.admin_client.post_rotate_llm_secret")
    @patch("jarvis.admin_client.post_update_llm_creds")
    def test_reload_action_calls_rotate_llm_secret(self, mock_update, mock_rotate):
        mock_rotate.return_value = {"action": "reload"}
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("llm_api_key", "sk-1", update_modified=False)
        frappe.db.commit()
        settings.reload()
        settings._sync_via_admin("reload")
        mock_rotate.assert_called_once_with(secret="sk-1")
        mock_update.assert_not_called()

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
        mock_rotate.assert_not_called()

    @patch("jarvis.admin_client.post_rotate_llm_secret")
    @patch("jarvis.admin_client.post_update_llm_creds")
    def test_restart_oauth_threads_auth_mode(self, mock_update, mock_rotate):
        """Oauth-mode restart still calls post_update_llm_creds; admin ignores
        api_key in oauth mode (credentials live in auth-profiles.json on the
        container). The bench just threads auth_mode through."""
        from frappe.utils.password import remove_encrypted_password
        mock_update.return_value = {"action": "restart"}
        # Clear llm_api_key so the wire payload reflects an unconfigured
        # api-key field (oauth mode tenants never set llm_api_key).
        remove_encrypted_password("Jarvis Settings", "Jarvis Settings", "llm_api_key")
        frappe.db.set_single_value("Jarvis Settings", "llm_api_key", None)
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("llm_auth_mode", "oauth", update_modified=False)
        settings.db_set("llm_provider", "OpenAI", update_modified=False)
        frappe.db.commit()
        settings.reload()
        settings._sync_via_admin("restart")
        kw = mock_update.call_args.kwargs
        self.assertEqual(kw["auth_mode"], "oauth")
        self.assertEqual(kw["api_key"], "")
        mock_rotate.assert_not_called()

    @patch("jarvis.admin_client.post_rotate_llm_secret")
    def test_rate_limited_is_logged_not_raised(self, mock_rotate):
        from jarvis.exceptions import AdminRateLimitedError
        mock_rotate.side_effect = AdminRateLimitedError(retry_after_seconds=600)
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("llm_api_key", "sk-1", update_modified=False)
        frappe.db.commit()
        settings.reload()
        before_status = settings.last_sync_status
        # Should not raise.
        settings._sync_via_admin("reload")
        # last_sync_status unchanged (rate-limit is a bench-side bug, not creds).
        settings.reload()
        self.assertEqual(settings.last_sync_status, before_status)

    @patch("jarvis.admin_client.post_rotate_llm_secret")
    def test_admin_auth_error_recorded_in_status(self, mock_rotate):
        from jarvis.exceptions import AdminAuthError
        mock_rotate.side_effect = AdminAuthError("not onboarded")
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("llm_api_key", "sk-1", update_modified=False)
        frappe.db.commit()
        settings.reload()
        settings._sync_via_admin("reload")
        settings.reload()
        self.assertIn("failed", settings.last_sync_status or "")
        self.assertIn("auth", settings.last_sync_status or "")


class TestOnUpdateAsyncPending(_SettingsSingletonTestCase):
    """The async path writes ``last_sync_status = 'pending: ...'``
    synchronously, then enqueues the admin call. In tests we normally run
    the enqueue inline (via ``frappe.flags.in_test``), so the final status
    overwrites the pending marker. This class explicitly stops the inline
    behavior to verify the intermediate "pending:" write happens BEFORE
    ``_sync_via_admin`` fires."""

    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_pending_status_written_before_enqueue_for_reload(self):
        seen = []

        def capture_pending(*args, **kwargs):
            # Called from _enqueued_sync_via_admin via frappe.enqueue(now=True).
            # By the time this runs, the synchronous "pending:" db_set in
            # on_update should already be persisted.
            settings = frappe.get_single("Jarvis Settings")
            seen.append(settings.last_sync_status)
            # Now simulate the admin call's final status write.
            settings.db_set("last_sync_status", "ok (reload via admin)",
                            update_modified=False)
            return {"action": "reload"}

        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-rotation"
        with patch("jarvis.admin_client.post_rotate_llm_secret",
                   side_effect=capture_pending):
            settings.save()
        self.assertEqual(len(seen), 1)
        self.assertTrue(
            (seen[0] or "").startswith("pending: rotating credentials"),
            f"expected 'pending: rotating credentials', got {seen[0]!r}",
        )

    def test_pending_status_written_before_enqueue_for_restart(self):
        seen = []

        def capture_pending(*args, **kwargs):
            settings = frappe.get_single("Jarvis Settings")
            seen.append(settings.last_sync_status)
            settings.db_set("last_sync_status", "ok (restart via admin)",
                            update_modified=False)
            return {"action": "restart"}

        settings = frappe.get_single("Jarvis Settings")
        settings.llm_provider = "Anthropic"
        settings.llm_model = "claude-sonnet-4-6"
        with patch("jarvis.admin_client.post_update_llm_creds",
                   side_effect=capture_pending):
            settings.save()
        self.assertEqual(len(seen), 1)
        self.assertTrue(
            (seen[0] or "").startswith("pending: provisioning container"),
            f"expected 'pending: provisioning container', got {seen[0]!r}",
        )
