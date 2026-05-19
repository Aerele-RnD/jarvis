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

    def test_llm_provider_options_cover_paid_and_open_weight(self):
        meta = frappe.get_meta("Jarvis Settings")
        provider_field = next(f for f in meta.fields if f.fieldname == "llm_provider")
        self.assertEqual(provider_field.fieldtype, "Select")
        options = {line.strip() for line in (provider_field.options or "").splitlines() if line.strip()}
        missing = EXPECTED_PROVIDERS - options
        self.assertFalse(missing, f"llm_provider missing options: {missing}")

    def test_operator_tab_fields(self):
        meta = frappe.get_meta("Jarvis Settings")
        fields_by_name = {f.fieldname: f for f in meta.fields}

        # Tab break + section break
        self.assertEqual(fields_by_name["operator_tab"].fieldtype, "Tab Break")
        self.assertEqual(fields_by_name["operator_section"].fieldtype, "Section Break")
        self.assertEqual(fields_by_name["last_sync_section"].fieldtype, "Section Break")

        # Operator fields
        self.assertEqual(fields_by_name["agent_url"].fieldtype, "Data")
        self.assertEqual(fields_by_name["agent_token"].fieldtype, "Password")
        self.assertEqual(fields_by_name["agent_llm_key_path"].fieldtype, "Data")
        self.assertEqual(fields_by_name["agent_config_path"].fieldtype, "Data")
        self.assertEqual(fields_by_name["agent_compose_dir"].fieldtype, "Data")

        # Readonly status fields
        self.assertEqual(fields_by_name["last_sync_at"].fieldtype, "Datetime")
        self.assertTrue(fields_by_name["last_sync_at"].read_only)
        self.assertEqual(fields_by_name["last_sync_status"].fieldtype, "Long Text")
        self.assertTrue(fields_by_name["last_sync_status"].read_only)
