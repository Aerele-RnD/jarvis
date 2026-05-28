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
        self.llm_auth_mode = kwargs.get("llm_auth_mode", "api_key")
        self.llm_oauth_access_token = kwargs.get("llm_oauth_access_token")


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

    def test_base_url_falls_back_to_provider_default_when_setting_empty(self):
        # openclaw's schema requires baseUrl on every provider entry — we always emit it.
        # When the customer hasn't set llm_base_url, we use the bundled-provider default.
        result, _ = self._render(llm_provider="Anthropic", llm_model="claude-sonnet-4-6")
        self.assertEqual(
            result["models"]["providers"]["anthropic"]["baseUrl"],
            "https://api.anthropic.com",
        )

    def test_models_array_includes_configured_model(self):
        # openclaw's schema requires each entry in `models` to have both `id` and `name`
        # (z.string().min(1) on each, .strict() rejects extras).
        result, _ = self._render(llm_provider="Moonshot (Kimi)", llm_model="kimi-k2.6")
        models = result["models"]["providers"]["moonshot"]["models"]
        self.assertEqual(models, [{"id": "kimi-k2.6", "name": "kimi-k2.6"}])

    def test_vllm_without_base_url_raises(self):
        # vLLM has no default baseUrl in our PROVIDER_DEFAULT_BASE_URLS; customer must supply one.
        with self.assertRaises(InvalidArgumentError):
            render_config(
                _FakeSettings(llm_provider="vLLM (local)", llm_model="llama-3"),
                gateway_token="t",
            )

    def test_openai_compatible_without_base_url_raises(self):
        with self.assertRaises(InvalidArgumentError):
            render_config(
                _FakeSettings(llm_provider="OpenAI-Compatible", llm_model="any"),
                gateway_token="t",
            )

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
        # Providers without a bundled default base URL need one explicitly supplied
        providers_needing_base_url = {"vLLM (local)", "OpenAI-Compatible"}
        for human, openclaw_id in cases.items():
            base_url = "http://explicit:8000/v1" if human in providers_needing_base_url else None
            result, _ = self._render(
                llm_provider=human,
                llm_model="some-model",
                llm_base_url=base_url,
            )
            self.assertIn(openclaw_id, result["models"]["providers"], f"{human} -> {openclaw_id}")
            self.assertEqual(
                result["agents"]["defaults"]["model"]["primary"],
                f"{openclaw_id}/some-model",
            )
            # All providers must have baseUrl emitted (schema requirement)
            self.assertIn("baseUrl", result["models"]["providers"][openclaw_id])

    # --- Path A: agentRuntime + plugins.entries; no mcp block ---

    def test_agent_runtime_is_pi_for_active_provider(self):
        result, _ = self._render(llm_provider="Moonshot (Kimi)", llm_model="kimi-k2.6")
        provider_entry = result["models"]["providers"]["moonshot"]
        self.assertEqual(provider_entry["agentRuntime"], {"id": "pi"})

    def test_agent_runtime_is_pi_for_all_providers(self):
        providers_needing_base_url = {"vLLM (local)", "OpenAI-Compatible"}
        for human, openclaw_id in PROVIDER_MAP.items():
            base_url = "http://explicit:8000/v1" if human in providers_needing_base_url else None
            result, _ = self._render(
                llm_provider=human,
                llm_model="some-model",
                llm_base_url=base_url,
            )
            provider_entry = result["models"]["providers"][openclaw_id]
            self.assertEqual(
                provider_entry.get("agentRuntime"),
                {"id": "pi"},
                f"{human} -> {openclaw_id} missing agentRuntime.id='pi'",
            )

    def test_no_mcp_block(self):
        """Path A removes the mcp.servers.jarvis surface — tools are registered via the plugin."""
        result, _ = self._render(llm_provider="Moonshot (Kimi)", llm_model="kimi-k2.6")
        self.assertNotIn("mcp", result)

    def test_plugins_block_registers_jarvis_plugin(self):
        result, _ = self._render(llm_provider="Moonshot (Kimi)", llm_model="kimi-k2.6")
        self.assertIn("plugins", result)
        self.assertIn("jarvis-openclaw-plugin", result["plugins"]["entries"])

    def test_plugins_block_present_for_stub_fallback(self):
        # Even in stub mode (no provider configured), the plugin entry must be present
        result, _ = self._render(llm_provider=None, llm_model=None)
        self.assertIn("plugins", result)
        self.assertIn("jarvis-openclaw-plugin", result["plugins"]["entries"])


class TestRenderConfigSubscription(FrappeTestCase):
    def _render(self, **kwargs):
        return json.loads(render_config(_FakeSettings(**kwargs), gateway_token="GW-1"))

    def test_api_key_mode_emits_api_key_auth(self):
        out = self._render(llm_provider="OpenAI", llm_model="gpt-4o-mini")
        provider_block = out["models"]["providers"]["openai"]
        self.assertEqual(provider_block.get("authMode"), "api_key")

    def test_subscription_mode_emits_subscription_auth(self):
        out = self._render(
            llm_provider="OpenAI",
            llm_model="gpt-4o-mini",
            llm_auth_mode="subscription",
            llm_oauth_access_token="AT-1",
        )
        provider_block = out["models"]["providers"]["openai"]
        self.assertEqual(provider_block.get("authMode"), "subscription")

    def test_subscription_mode_empty_token_falls_back_to_stub(self):
        out = self._render(
            llm_provider="OpenAI",
            llm_model="gpt-4o-mini",
            llm_auth_mode="subscription",
            llm_oauth_access_token=None,
        )
        # Falls back to STUB_DEFAULTS — moonshot per current stub
        stub_id = STUB_DEFAULTS["provider_id"]
        self.assertIn(stub_id, out["models"]["providers"])
        # And the rendered mode reverts to api_key since the stub has no subscription
        self.assertEqual(out["models"]["providers"][stub_id].get("authMode"), "api_key")
