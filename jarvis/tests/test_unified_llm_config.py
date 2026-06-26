"""Tests for Task 1: Unified LLM config — Jarvis Settings schema assertions.

Verifies:
- Jarvis Settings has models (Table), preset (Select), proxy_active (Check, read_only),
  proxy_recommended (Check, read_only) fields
- Legacy llm_model, llm_api_key, llm_provider, llm_base_url, llm_auth_mode are read_only
- Standalone Jarvis LLM Pool doctype no longer exists
- Pool Model provider + base_url fields have depends_on on credential_type=='api_key'
- Subscription Account upstream options do NOT contain 'anthropic'
"""

import frappe
from frappe.tests.utils import FrappeTestCase


def _field_map(meta):
    """Return a dict of fieldname -> field dict from a Meta object."""
    return {f.fieldname: f for f in meta.fields}


class TestUnifiedLLMConfigSchema(FrappeTestCase):
    """Schema-level assertions for the unified LLM config design."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.settings_meta = frappe.get_meta("Jarvis Settings")
        cls.settings_fields = _field_map(cls.settings_meta)
        cls.pool_model_meta = frappe.get_meta("Jarvis LLM Pool Model")
        cls.pool_model_fields = _field_map(cls.pool_model_meta)
        cls.sub_account_meta = frappe.get_meta("Jarvis LLM Pool Subscription Account")
        cls.sub_account_fields = _field_map(cls.sub_account_meta)

    # ------------------------------------------------------------------ #
    # Jarvis Settings — new fields
    # ------------------------------------------------------------------ #

    def test_settings_has_models_table_field(self):
        """Jarvis Settings must have a 'models' Table field pointing to Jarvis LLM Pool Model."""
        self.assertIn("models", self.settings_fields,
                      "Jarvis Settings must have a 'models' field")
        f = self.settings_fields["models"]
        self.assertEqual(f.fieldtype, "Table",
                         "models field must be of type Table")
        self.assertEqual(f.options, "Jarvis LLM Pool Model",
                         "models Table must link to 'Jarvis LLM Pool Model'")

    def test_settings_has_preset_select_field(self):
        """Jarvis Settings must have a 'preset' Select field."""
        self.assertIn("preset", self.settings_fields,
                      "Jarvis Settings must have a 'preset' field")
        f = self.settings_fields["preset"]
        self.assertEqual(f.fieldtype, "Select",
                         "preset field must be of type Select")

    def test_settings_has_proxy_active_check_read_only(self):
        """Jarvis Settings must have 'proxy_active' Check field that is read_only."""
        self.assertIn("proxy_active", self.settings_fields,
                      "Jarvis Settings must have a 'proxy_active' field")
        f = self.settings_fields["proxy_active"]
        self.assertEqual(f.fieldtype, "Check",
                         "proxy_active must be of type Check")
        self.assertEqual(f.read_only, 1,
                         "proxy_active must be read_only=1")

    def test_settings_has_proxy_recommended_check_read_only(self):
        """Jarvis Settings must have 'proxy_recommended' Check field that is read_only."""
        self.assertIn("proxy_recommended", self.settings_fields,
                      "Jarvis Settings must have a 'proxy_recommended' field")
        f = self.settings_fields["proxy_recommended"]
        self.assertEqual(f.fieldtype, "Check",
                         "proxy_recommended must be of type Check")
        self.assertEqual(f.read_only, 1,
                         "proxy_recommended must be read_only=1")

    # ------------------------------------------------------------------ #
    # Jarvis Settings — legacy fields become read_only
    # ------------------------------------------------------------------ #

    def test_llm_model_is_read_only(self):
        """Legacy llm_model field must be read_only=1 (derived mirror)."""
        self.assertIn("llm_model", self.settings_fields)
        self.assertEqual(self.settings_fields["llm_model"].read_only, 1,
                         "llm_model must be read_only=1")

    def test_llm_api_key_is_read_only(self):
        """Legacy llm_api_key field must be read_only=1 (derived mirror)."""
        self.assertIn("llm_api_key", self.settings_fields)
        self.assertEqual(self.settings_fields["llm_api_key"].read_only, 1,
                         "llm_api_key must be read_only=1")

    def test_llm_provider_is_read_only(self):
        """Legacy llm_provider field must be read_only=1 (derived mirror)."""
        self.assertIn("llm_provider", self.settings_fields)
        self.assertEqual(self.settings_fields["llm_provider"].read_only, 1,
                         "llm_provider must be read_only=1")

    def test_llm_base_url_is_read_only(self):
        """Legacy llm_base_url field must be read_only=1 (derived mirror)."""
        self.assertIn("llm_base_url", self.settings_fields)
        self.assertEqual(self.settings_fields["llm_base_url"].read_only, 1,
                         "llm_base_url must be read_only=1")

    def test_llm_auth_mode_is_read_only(self):
        """Legacy llm_auth_mode field must be read_only=1 (derived mirror)."""
        self.assertIn("llm_auth_mode", self.settings_fields)
        self.assertEqual(self.settings_fields["llm_auth_mode"].read_only, 1,
                         "llm_auth_mode must be read_only=1")

    # ------------------------------------------------------------------ #
    # Standalone Jarvis LLM Pool doctype must NOT exist
    # ------------------------------------------------------------------ #

    def test_standalone_llm_pool_doctype_dropped(self):
        """The standalone 'Jarvis LLM Pool' Single doctype must not exist."""
        exists = frappe.db.exists("DocType", "Jarvis LLM Pool")
        self.assertFalse(exists,
                        "Jarvis LLM Pool standalone doctype must be dropped")

    # ------------------------------------------------------------------ #
    # Pool Model — provider + base_url gated on credential_type
    # ------------------------------------------------------------------ #

    def test_pool_model_provider_has_depends_on_credential_type(self):
        """Pool Model 'provider' field must have depends_on gating on credential_type=='api_key'."""
        self.assertIn("provider", self.pool_model_fields)
        depends_on = self.pool_model_fields["provider"].depends_on or ""
        self.assertIn("credential_type", depends_on,
                      "provider field depends_on must reference credential_type")

    def test_pool_model_base_url_has_depends_on_credential_type(self):
        """Pool Model 'base_url' field must have depends_on gating on credential_type=='api_key'."""
        self.assertIn("base_url", self.pool_model_fields)
        depends_on = self.pool_model_fields["base_url"].depends_on or ""
        self.assertIn("credential_type", depends_on,
                      "base_url field depends_on must reference credential_type")

    # ------------------------------------------------------------------ #
    # Subscription Account — upstream must not include 'anthropic'
    # ------------------------------------------------------------------ #

    def test_subscription_account_upstream_no_anthropic(self):
        """Subscription Account 'upstream' options must NOT contain 'anthropic' (ToS-banned)."""
        self.assertIn("upstream", self.sub_account_fields)
        options = self.sub_account_fields["upstream"].options or ""
        option_list = [o.strip() for o in options.split("\n") if o.strip()]
        self.assertNotIn("anthropic", option_list,
                         "upstream options must not include 'anthropic' (ToS violation)")
