from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import OpenclawReloadFailedError, OpenclawUnreachableError


# Field defaults that mark operator config as "complete"
OPERATOR_COMPLETE = {
    "openclaw_gateway_url": "ws://127.0.0.1:18789",
    "openclaw_gateway_token": "test-token-abc",
    "openclaw_llm_key_path": "/tmp/jarvis-test/llm.key",
    "openclaw_config_path": "/tmp/jarvis-test/openclaw.json",
    "openclaw_compose_dir": "/tmp/jarvis-test/openclaw",
}

LLM_BASELINE = {
    "llm_provider": "Moonshot (Kimi)",
    "llm_model": "kimi-k2.6",
    "llm_api_key": "sk-original-1234",
    "llm_base_url": "",
}


def _reset_settings():
    settings = frappe.get_single("Jarvis Settings")
    # Use db_set to set up state without triggering on_update
    for field, value in {**OPERATOR_COMPLETE, **LLM_BASELINE, "last_sync_status": "", "last_sync_at": None}.items():
        settings.db_set(field, value)
    frappe.db.commit()


class TestOnUpdateClassification(FrappeTestCase):
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


class TestOnUpdateOperatorGate(FrappeTestCase):
    def setUp(self):
        super().setUp()
        _reset_settings()

    def test_missing_gateway_url_skips(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("openclaw_gateway_url", "")
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
        settings.db_set("openclaw_gateway_token", "")
        frappe.db.commit()
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_api_key = "sk-new"
        with patch("jarvis.openclaw_push.push_creds_reload") as reload_mock:
            settings.save()
            self.assertFalse(reload_mock.called)

    def test_missing_compose_dir_skips_restart(self):
        settings = frappe.get_single("Jarvis Settings")
        settings.db_set("openclaw_compose_dir", "")
        frappe.db.commit()
        settings = frappe.get_single("Jarvis Settings")
        settings.llm_provider = "Anthropic"
        settings.llm_model = "claude-sonnet-4-6"
        with patch("jarvis.openclaw_push.push_creds_restart") as restart_mock:
            settings.save()
            self.assertFalse(restart_mock.called)


class TestOnUpdateStatus(FrappeTestCase):
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
