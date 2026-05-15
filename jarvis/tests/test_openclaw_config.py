import json

from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError
from jarvis.openclaw_config import PROVIDER_MAP, STUB_DEFAULTS, render_config


class _FakeSettings:
    """Plain-attribute stand-in for a Jarvis Settings doc; avoids needing a Frappe DB round-trip."""

    def __init__(self, **kwargs):
        self.llm_provider = kwargs.get("llm_provider")
        self.llm_model = kwargs.get("llm_model")
        self.llm_base_url = kwargs.get("llm_base_url")


class TestProviderMap(FrappeTestCase):
    def test_all_jarvis_settings_providers_are_mapped(self):
        expected = {
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
        self.assertEqual(set(PROVIDER_MAP.keys()), expected)

    def test_provider_ids_are_lowercase_and_alphanumeric(self):
        # openclaw provider-id regex: ^[a-z][a-z0-9_-]{0,63}$
        import re
        rx = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
        for human, openclaw_id in PROVIDER_MAP.items():
            self.assertRegex(openclaw_id, rx, f"{human} -> {openclaw_id} fails openclaw id regex")


class TestRenderConfig(FrappeTestCase):
    def _render(self, **kwargs):
        token = "test-gateway-token-abc123"
        config = render_config(_FakeSettings(**kwargs), gateway_token=token)
        return json.loads(config), token

    def test_renders_valid_json(self):
        result, _ = self._render(llm_provider="Moonshot (Kimi)", llm_model="kimi-k2.6")
        self.assertIn("gateway", result)
        self.assertIn("models", result)
        self.assertIn("secrets", result)

    def test_gateway_block_has_required_fields(self):
        result, token = self._render(llm_provider="Moonshot (Kimi)", llm_model="kimi-k2.6")
        self.assertEqual(result["gateway"]["mode"], "local")
        self.assertEqual(result["gateway"]["port"], 18789)
        self.assertEqual(result["gateway"]["bind"], "lan")
        self.assertEqual(result["gateway"]["auth"]["mode"], "token")
        self.assertEqual(result["gateway"]["auth"]["token"], token)
        self.assertTrue(result["gateway"]["http"]["endpoints"]["chatCompletions"]["enabled"])
        self.assertTrue(result["gateway"]["http"]["endpoints"]["responses"]["enabled"])

    def test_agents_default_model_primary_is_provider_slash_model(self):
        result, _ = self._render(llm_provider="Moonshot (Kimi)", llm_model="kimi-k2.6")
        self.assertEqual(result["agents"]["defaults"]["model"]["primary"], "moonshot/kimi-k2.6")

    def test_active_provider_entry_uses_secret_ref_for_api_key(self):
        result, _ = self._render(llm_provider="Anthropic", llm_model="claude-sonnet-4-6")
        provider_entry = result["models"]["providers"]["anthropic"]
        self.assertEqual(provider_entry["apiKey"], {"source": "file", "provider": "llm_key", "id": "value"})

    def test_no_type_field_on_provider_entry(self):
        # openclaw does not accept a `type` field on models.providers.<id>
        result, _ = self._render(llm_provider="OpenAI", llm_model="gpt-4o")
        self.assertNotIn("type", result["models"]["providers"]["openai"])

    def test_no_default_provider_or_default_model_legacy_keys(self):
        result, _ = self._render(llm_provider="OpenAI", llm_model="gpt-4o")
        self.assertNotIn("defaultProvider", result["models"])
        self.assertNotIn("defaultModel", result["models"]["providers"]["openai"])

    def test_base_url_included_when_set(self):
        result, _ = self._render(
            llm_provider="Ollama (local)",
            llm_model="llama-3.1-70b",
            llm_base_url="http://host.docker.internal:11434/v1",
        )
        self.assertEqual(
            result["models"]["providers"]["ollama"]["baseUrl"],
            "http://host.docker.internal:11434/v1",
        )

    def test_base_url_omitted_when_empty(self):
        result, _ = self._render(llm_provider="Anthropic", llm_model="claude-sonnet-4-6")
        self.assertNotIn("baseUrl", result["models"]["providers"]["anthropic"])

    def test_secrets_block_registers_singlevalue_file_provider(self):
        result, _ = self._render(llm_provider="Anthropic", llm_model="claude-sonnet-4-6")
        secrets_provider = result["secrets"]["providers"]["llm_key"]
        self.assertEqual(secrets_provider["source"], "file")
        self.assertEqual(secrets_provider["mode"], "singleValue")
        self.assertEqual(secrets_provider["path"], "/home/node/.openclaw/llm.key")

    def test_channels_empty_object(self):
        result, _ = self._render(llm_provider="Anthropic", llm_model="claude-sonnet-4-6")
        self.assertEqual(result["channels"], {})

    def test_stub_fallback_when_no_provider_set(self):
        # Empty Settings: render falls back to STUB_DEFAULTS so openclaw still boots
        result, _ = self._render(llm_provider=None, llm_model=None)
        primary = result["agents"]["defaults"]["model"]["primary"]
        self.assertEqual(primary, f"{STUB_DEFAULTS['provider_id']}/{STUB_DEFAULTS['model']}")
        self.assertIn(STUB_DEFAULTS["provider_id"], result["models"]["providers"])

    def test_unknown_provider_raises(self):
        with self.assertRaises(InvalidArgumentError):
            render_config(
                _FakeSettings(llm_provider="Not A Real Provider", llm_model="x"),
                gateway_token="t",
            )

    def test_all_twelve_providers_render(self):
        # Sanity: each known provider name produces valid JSON with the expected provider_id
        cases = {
            "Anthropic": "anthropic",
            "OpenAI": "openai",
            "Google Gemini": "google",
            "Mistral": "mistral",
            "Groq": "groq",
            "Together AI": "together",
            "DeepSeek": "deepseek",
            "Moonshot (Kimi)": "moonshot",
            "OpenRouter": "openrouter",
            "Ollama (local)": "ollama",
            "vLLM (local)": "vllm",
            "OpenAI-Compatible": "openai_compat",
        }
        for human, openclaw_id in cases.items():
            result, _ = self._render(llm_provider=human, llm_model="some-model")
            self.assertIn(openclaw_id, result["models"]["providers"], f"{human} -> {openclaw_id}")
            self.assertEqual(
                result["agents"]["defaults"]["model"]["primary"],
                f"{openclaw_id}/some-model",
            )
