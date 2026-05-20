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


class TestOnUpdateAdminDispatch(FrappeTestCase):
	"""Tests for the admin-path branch added in Plan 3.2.2b.

	When jarvis_admin_url is set, on_update routes through
	jarvis.admin_client.post_update_llm_creds instead of openclaw_push.
	Errors land in last_sync_status; save itself never raises.
	"""

	def setUp(self):
		self.settings = frappe.get_single("Jarvis Settings")
		# Snapshot fields we'll mutate so tearDown can restore
		self._original_admin_url = self.settings.jarvis_admin_url or ""
		self._original_admin_key = self.settings.get_password("jarvis_admin_api_key", raise_exception=False) or ""
		# Set the admin path "on"
		self.settings.db_set("jarvis_admin_url", "https://admin.example.com")
		self.settings.db_set("jarvis_admin_api_key", "test-token")
		# Set a known llm_provider so changing api_key triggers reload
		self.settings.db_set("llm_provider", "Anthropic")
		self.settings.db_set("llm_model", "claude-sonnet-4-6")
		self.settings.db_set("llm_base_url", "https://api.anthropic.com")
		self.settings.db_set("llm_api_key", "sk-original")
		frappe.db.commit()

	def tearDown(self):
		s = frappe.get_single("Jarvis Settings")
		s.db_set("jarvis_admin_url", self._original_admin_url)
		s.db_set("jarvis_admin_api_key", self._original_admin_key)
		frappe.db.commit()

	def _save_with_new_api_key(self, new_key="sk-new"):
		# Re-fetch + change llm_api_key, then save (triggers on_update).
		s = frappe.get_doc("Jarvis Settings", "Jarvis Settings")
		s.llm_api_key = new_key
		s.save(ignore_permissions=True)
		frappe.db.commit()
		return frappe.get_doc("Jarvis Settings", "Jarvis Settings")

	def test_admin_path_reload_success_updates_last_sync_status(self):
		from unittest.mock import patch
		with patch("jarvis.admin_client.post_update_llm_creds",
				   return_value={"action": "reload", "result": "ok"}) as mock_post:
			s = self._save_with_new_api_key("sk-after-reload-test")
		mock_post.assert_called_once()
		self.assertEqual(s.last_sync_status, "ok (reload via admin)")
		self.assertIsNotNone(s.last_sync_at)

	def test_admin_path_restart_returned_action_reflects_in_status(self):
		from unittest.mock import patch
		with patch("jarvis.admin_client.post_update_llm_creds",
				   return_value={"action": "restart", "result": "ok"}):
			# Trigger via a change that classifies as restart (provider change)
			s = frappe.get_doc("Jarvis Settings", "Jarvis Settings")
			s.llm_provider = "OpenAI"
			s.llm_model = "gpt-4o"
			s.llm_base_url = "https://api.openai.com"
			s.llm_api_key = "sk-openai"
			s.save(ignore_permissions=True)
			frappe.db.commit()
			s = frappe.get_doc("Jarvis Settings", "Jarvis Settings")
		self.assertEqual(s.last_sync_status, "ok (restart via admin)")

	def test_admin_path_auth_error_surfaces_in_status(self):
		from unittest.mock import patch
		from jarvis.exceptions import AdminAuthError
		with patch("jarvis.admin_client.post_update_llm_creds",
				   side_effect=AdminAuthError("invalid token")):
			s = self._save_with_new_api_key("sk-auth-fail-test")
		self.assertTrue(s.last_sync_status.startswith("failed: auth:"))
		self.assertIn("invalid token", s.last_sync_status)

	def test_admin_path_unreachable_surfaces_in_status(self):
		from unittest.mock import patch
		from jarvis.exceptions import AdminUnreachableError
		with patch("jarvis.admin_client.post_update_llm_creds",
				   side_effect=AdminUnreachableError("connection refused")):
			s = self._save_with_new_api_key("sk-unreach-test")
		self.assertTrue(s.last_sync_status.startswith("failed: admin unreachable:"))
		self.assertIn("connection refused", s.last_sync_status)


class TestOnUpdateLocalDispatchWhenAdminUrlEmpty(FrappeTestCase):
	"""Verify the dispatcher routes to the local path when jarvis_admin_url is
	empty (the dev / Phase 1 invariant)."""

	def setUp(self):
		s = frappe.get_single("Jarvis Settings")
		self._original_admin_url = s.jarvis_admin_url or ""
		s.db_set("jarvis_admin_url", "")
		# Local path needs operator fields configured too — populate with stubs
		s.db_set("agent_url", "ws://localhost:18789")
		s.db_set("agent_token", "stub-token")
		s.db_set("agent_llm_key_path", "/tmp/stub-key")
		s.db_set("agent_config_path", "/tmp/stub-config.json")
		s.db_set("agent_compose_dir", "/tmp/stub-compose")
		s.db_set("llm_provider", "Anthropic")
		s.db_set("llm_model", "claude-sonnet-4-6")
		s.db_set("llm_base_url", "https://api.anthropic.com")
		s.db_set("llm_api_key", "sk-original-local")
		frappe.db.commit()

	def tearDown(self):
		s = frappe.get_single("Jarvis Settings")
		s.db_set("jarvis_admin_url", self._original_admin_url)
		frappe.db.commit()

	def test_local_path_invoked_when_admin_url_empty(self):
		from unittest.mock import patch
		# Mock both possible entry points; only the local one should be called.
		with patch("jarvis.openclaw_push.push_creds_reload") as local_mock, \
			 patch("jarvis.admin_client.post_update_llm_creds") as admin_mock:
			s = frappe.get_doc("Jarvis Settings", "Jarvis Settings")
			s.llm_api_key = "sk-new-local"
			s.save(ignore_permissions=True)
			frappe.db.commit()
		local_mock.assert_called_once()
		admin_mock.assert_not_called()
