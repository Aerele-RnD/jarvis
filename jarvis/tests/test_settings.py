import frappe
from frappe.tests.utils import FrappeTestCase


EXPECTED_PROVIDERS = {
    "Anthropic",
    "OpenAI",
    "Google Gemini",
    "Mistral",
    "Groq",
    "Together AI",
    "DeepSeek",
    "Moonshot (Kimi)",
    "OpenRouter",
    "Ollama (local)",
    "vLLM (local)",
    "OpenAI-Compatible",
}


class TestJarvisSettings(FrappeTestCase):
    def test_settings_is_single(self):
        meta = frappe.get_meta("Jarvis Settings")
        self.assertTrue(meta.issingle, "Jarvis Settings must be a Single DocType")

    def test_settings_has_expected_fields(self):
        meta = frappe.get_meta("Jarvis Settings")
        fieldnames = {f.fieldname for f in meta.fields}
        required = (
            "jarvis_admin_api_key",
            "jarvis_admin_url",
            "token_budget_monthly",
            "llm_provider",
            "llm_model",
            "llm_api_key",
            "llm_base_url",
            "llm_temperature",
            "llm_max_output_tokens",
        )
        for fieldname in required:
            self.assertIn(fieldname, fieldnames, f"missing field: {fieldname}")

    def test_api_keys_are_password_fields(self):
        meta = frappe.get_meta("Jarvis Settings")
        for fieldname in ("jarvis_admin_api_key", "llm_api_key"):
            field = next(f for f in meta.fields if f.fieldname == fieldname)
            self.assertEqual(field.fieldtype, "Password", f"{fieldname} must be Password")

    def test_jarvis_admin_fields_are_readonly(self):
        """Populated by the signup wizard / staff; never customer-edited."""
        meta = frappe.get_meta("Jarvis Settings")
        for fieldname in ("jarvis_admin_url", "jarvis_admin_api_key"):
            field = next(f for f in meta.fields if f.fieldname == fieldname)
            self.assertTrue(
                field.read_only,
                f"{fieldname} must be read-only (populated by signup wizard)",
            )

    def test_llm_provider_options_cover_paid_and_open_weight(self):
        meta = frappe.get_meta("Jarvis Settings")
        provider_field = next(f for f in meta.fields if f.fieldname == "llm_provider")
        self.assertEqual(provider_field.fieldtype, "Select")
        options = {line.strip() for line in (provider_field.options or "").splitlines() if line.strip()}
        missing = EXPECTED_PROVIDERS - options
        self.assertFalse(missing, f"llm_provider missing options: {missing}")

    def test_tab_structure(self):
        """Two tabs: Configuration (editable) and System (read-only)."""
        meta = frappe.get_meta("Jarvis Settings")
        fields_by_name = {f.fieldname: f for f in meta.fields}

        self.assertEqual(fields_by_name["config_tab"].fieldtype, "Tab Break")
        self.assertEqual(fields_by_name["config_tab"].label, "Configuration")
        self.assertEqual(fields_by_name["system_tab"].fieldtype, "Tab Break")
        self.assertEqual(fields_by_name["system_tab"].label, "System")

    def test_configuration_tab_sections(self):
        """Configuration tab has Account, Language Model, Sampling sections."""
        meta = frappe.get_meta("Jarvis Settings")
        fields_by_name = {f.fieldname: f for f in meta.fields}

        for fieldname in ("account_section", "llm_section", "llm_advanced_section"):
            self.assertEqual(fields_by_name[fieldname].fieldtype, "Section Break")

    def test_system_tab_sections(self):
        """System tab has Jarvis Admin Connection, Agent Operator, Last Sync sections."""
        meta = frappe.get_meta("Jarvis Settings")
        fields_by_name = {f.fieldname: f for f in meta.fields}

        for fieldname in ("admin_connection_section", "operator_section", "last_sync_section"):
            self.assertEqual(fields_by_name[fieldname].fieldtype, "Section Break")

    def test_operator_fields_are_readonly(self):
        """All 5 operator fields are system-populated and must be read-only."""
        meta = frappe.get_meta("Jarvis Settings")
        fields_by_name = {f.fieldname: f for f in meta.fields}

        for fieldname, expected_type in (
            ("agent_url", "Data"),
            ("agent_token", "Password"),
            ("agent_llm_key_path", "Data"),
            ("agent_config_path", "Data"),
            ("agent_compose_dir", "Data"),
        ):
            self.assertEqual(fields_by_name[fieldname].fieldtype, expected_type)
            self.assertTrue(
                fields_by_name[fieldname].read_only,
                f"{fieldname} must be read-only (system-populated by openclaw_bootstrap / admin signup)",
            )

    def test_last_sync_fields_are_readonly(self):
        meta = frappe.get_meta("Jarvis Settings")
        fields_by_name = {f.fieldname: f for f in meta.fields}

        self.assertEqual(fields_by_name["last_sync_at"].fieldtype, "Datetime")
        self.assertTrue(fields_by_name["last_sync_at"].read_only)
        self.assertEqual(fields_by_name["last_sync_status"].fieldtype, "Long Text")
        self.assertTrue(fields_by_name["last_sync_status"].read_only)
