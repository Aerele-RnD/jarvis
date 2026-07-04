from unittest.mock import patch
import frappe
from jarvis import onboarding, admin_client
from jarvis.tests.test_unified_llm_config import _RT3SettingsTestCase
from jarvis.tests.test_settings_on_update import _reset_settings

_CATALOG = [{"key": "cost-saver", "label": "Cost-saver", "kind": "cross_vendor",
             "blurb": "", "enabled": True, "vendors": ["openai"], "models": []}]


class TestSaveLlmPool(_RT3SettingsTestCase):
    def setUp(self):
        super().setUp()
        self._clear_models()
        _reset_settings()
        s = frappe.get_single("Jarvis Settings")
        s.db_set("preset", "", update_modified=False)
        s.db_set("routing_mode", "failover", update_modified=False)
        s.db_set("proxy_active", 0, update_modified=False)
        frappe.db.commit()

    def test_two_models_writes_rows_and_routes_to_proxy(self):
        models = [
            {"provider": "openai", "model": "gpt-5.5", "api_key": "sk-a", "base_url": "", "tier": "strong", "order": 0},
            {"provider": "openai", "model": "gpt-5.4", "api_key": "sk-b", "base_url": "", "tier": "strong", "order": 1},
        ]
        pool_calls = []
        with patch("jarvis.admin_client.post_update_llm_pool",
                   side_effect=lambda **kw: pool_calls.append(kw) or {"action": "pool_update"}), \
             patch("jarvis.admin_client.post_update_llm_creds") as creds:
            out = onboarding.save_llm_pool(frappe.as_json(models), preset=None, routing_mode="failover")
        self.assertTrue(pool_calls, "proxy pool path must fire for >=2 models")
        creds.assert_not_called()
        s = frappe.get_single("Jarvis Settings")
        self.assertEqual(len(s.get("models")), 2)
        self.assertEqual(s.models[0].get_password("api_key"), "sk-a")
        self.assertEqual(int(s.proxy_active or 0), 1)
        self.assertEqual(s.routing_mode, "failover")
        self.assertIn("last_sync_status", out)

    def test_one_model_no_preset_is_direct(self):
        models = [{"provider": "openai", "model": "gpt-5.5", "api_key": "sk-x", "base_url": "", "tier": "strong", "order": 0}]
        with patch("jarvis.admin_client.post_update_llm_creds", return_value={"action": "restart"}), \
             patch("jarvis.admin_client.post_update_llm_pool") as pool:
            onboarding.save_llm_pool(frappe.as_json(models))
        pool.assert_not_called()
        s = frappe.get_single("Jarvis Settings")
        self.assertEqual(int(s.proxy_active or 0), 0)

    def test_one_subscription_model_is_proxy(self):
        """A single chat-subscription model needs cliproxy → proxy path, NOT the
        DIRECT llm-creds path (which never serves the OAuth blob). #200 review #1."""
        models = [{
            "model": "gpt-5.5", "tier": "strong", "order": 0,
            "subscription": {"rotation": "sticky", "accounts": [
                {"upstream": "openai", "account_ref": "SUB_deadbeef",
                 "label": "me@x.com", "oauth_blob": '{"refresh_token":"rt"}'},
            ]},
        }]
        pool_calls = []
        with patch("jarvis.admin_client.post_update_llm_pool",
                   side_effect=lambda **kw: pool_calls.append(kw) or {"action": "pool_update"}), \
             patch("jarvis.admin_client.post_update_llm_creds") as creds:
            onboarding.save_llm_pool(frappe.as_json(models), preset=None, routing_mode="failover")
        self.assertTrue(pool_calls, "single subscription model must route to the proxy pool path")
        creds.assert_not_called()
        s = frappe.get_single("Jarvis Settings")
        self.assertEqual(int(s.proxy_active or 0), 1)
        # The account's blob reaches the pool push (served via cliproxy).
        self.assertEqual(pool_calls[0]["oauth_blobs"].get("SUB_deadbeef"), {"refresh_token": "rt"})

    def test_legacy_preset_value_normalized_by_patch(self):
        """A legacy capitalized Select value is mapped to its lowercase catalog
        key so the next save_llm_pool doesn't raise 'unknown preset'. #200 #12."""
        from jarvis.patches.v1_6_normalize_llm_preset_value import execute as normalize_preset
        s = frappe.get_single("Jarvis Settings")
        s.db_set("preset", "Balanced", update_modified=False)
        normalize_preset()
        s.reload()
        self.assertEqual(s.preset, "balanced")

    def test_preset_validated_against_catalog(self):
        models = [{"provider": "openai", "model": "gpt-5.5", "api_key": "sk-x", "base_url": "", "tier": "strong", "order": 0}]
        with patch("jarvis.admin_client.get_preset_catalog", return_value=_CATALOG):
            with self.assertRaises(frappe.ValidationError):
                onboarding.save_llm_pool(frappe.as_json(models), preset="does-not-exist")

    def test_non_failover_routing_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            onboarding.save_llm_pool(frappe.as_json([{"model": "m"}]), routing_mode="dynamic")

    def test_blank_key_surfaces_validation_error_from_pipeline(self):
        models = [
            {"provider": "openai", "model": "gpt-5.5", "api_key": "", "order": 0},
            {"provider": "openai", "model": "gpt-5.4", "api_key": "sk-b", "order": 1},
        ]
        with patch("jarvis.admin_client.post_update_llm_pool") as pool:
            with self.assertRaises(frappe.ValidationError):
                onboarding.save_llm_pool(frappe.as_json(models))
        pool.assert_not_called()  # on_update validate_models throws before enqueue


class TestGetLlmConfig(_RT3SettingsTestCase):
    def setUp(self):
        super().setUp()
        self._clear_models()
        _reset_settings()

    def test_reports_models_preset_routing_and_proxy_without_secrets(self):
        models = [
            {"provider": "openai", "model": "gpt-5.5", "api_key": "sk-a", "order": 0},
            {"provider": "openai", "model": "gpt-5.4", "api_key": "sk-b", "order": 1},
        ]
        with patch("jarvis.admin_client.post_update_llm_pool", return_value={"action": "pool_update"}):
            onboarding.save_llm_pool(frappe.as_json(models), routing_mode="failover")
        cfg = onboarding.get_llm_config()
        self.assertEqual(len(cfg["models"]), 2)
        self.assertEqual(cfg["models"][0]["model"], "gpt-5.5")
        self.assertTrue(cfg["models"][0]["has_key"])
        self.assertNotIn("api_key", cfg["models"][0])
        self.assertNotIn("sk-a", frappe.as_json(cfg))
        self.assertEqual(cfg["routing_mode"], "failover")
        self.assertTrue(cfg["proxy_active"])
