import frappe
from unittest.mock import patch
from frappe.tests.utils import FrappeTestCase

try:
    import llm_proxy as _llm_proxy_mod
    _HAS_LLM_PROXY = True
except ImportError:
    _HAS_LLM_PROXY = False

class TestJarvisLLMPool(FrappeTestCase):
    def test_pool_doctype_exists_and_is_single_sysmanager_only(self):
        assert frappe.db.exists("DocType", "Jarvis LLM Pool")
        meta = frappe.get_meta("Jarvis LLM Pool")
        assert meta.issingle == 1
        # System Manager is the only role with write
        perms = [p for p in frappe.get_all("DocPerm", filters={"parent": "Jarvis LLM Pool", "write": 1}, fields=["role"])]
        roles = {p["role"] for p in perms}
        assert roles == {"System Manager"}, roles

    def test_pool_model_child_fields(self):
        meta = frappe.get_meta("Jarvis LLM Pool Model")
        fields = {f.fieldname: f.fieldtype for f in meta.fields}
        for fn, ft in {"provider":"Data","model":"Data","tier":"Select","base_url":"Data",
                       "credential_type":"Select","api_key":"Password","order":"Int","enabled":"Check",
                       "rotation":"Select"}.items():
            assert fields.get(fn) == ft, (fn, fields.get(fn))

    def test_subscription_grandchild_fields(self):
        meta = frappe.get_meta("Jarvis LLM Pool Subscription Account")
        fields = {f.fieldname: f.fieldtype for f in meta.fields}
        for fn, ft in {"upstream":"Select","account_ref":"Data","label":"Data",
                       "oauth_blob":"Password"}.items():
            assert fields.get(fn) == ft, (fn, fields.get(fn))
        # rotation must NOT be on the account — it lives on the model row
        assert "rotation" not in fields, "rotation should be on model, not subscription account"

    def _make_test_pool(self):
        """Build an in-memory pool with 2 enabled models (one api_key, one subscription).

        Frappe child-table docs created via pool.append() have their
        _table_fieldnames overridden to an empty dict by the framework, so
        calling grandchild_row.append("accounts", ...) raises AttributeError.
        We work around this by injecting the accounts list directly as
        frappe._dict objects — the serialize functions only call m.get("accounts")
        and a.get_password() / attribute access, both of which work on _dict.
        """
        pool = frappe.get_single("Jarvis LLM Pool")
        pool.routing_mode = "dynamic"
        pool.set("models", [])
        pool.append("models", {"provider":"openai_compat","model":"claude-sonnet-4-6","tier":"strong",
                               "base_url":"http://host.docker.internal:9000/openai","credential_type":"api_key",
                               "api_key":"shimsecret","order":0,"enabled":1})
        pool.append("models", {"model":"gpt-5.5","tier":"cheap","credential_type":"subscription",
                               "rotation":"round_robin","order":1,"enabled":1})
        # Inject grandchild rows directly — pool.models[1].append() can't be used
        # on an unsaved child doc (Frappe sets _table_fieldnames to {} for child rows).
        account = frappe._dict(upstream="openai", account_ref="SUB_A1",
                               oauth_blob='{"t":1}', label="")
        pool.models[1].accounts = [account]
        return pool

    def test_build_pool_payload_and_auto_enable(self):
        from jarvis.jarvis.pool_serialize import build_pool_payload, compute_auto_enable
        pool = self._make_test_pool()
        spec, api_keys, oauth_blobs = build_pool_payload(pool)
        assert spec["routing_mode"] == "dynamic"
        assert spec["models"][0]["key_ref"] and spec["models"][0]["base_url"].endswith("/openai")
        sub = spec["models"][1]["subscription"]
        assert sub["upstream"] == "openai"
        # rotation lives on the subscription backing, not per-account
        assert sub["rotation"] == "round_robin"
        assert all("rotation" not in a for a in sub["accounts"])
        # secrets carried OUT of the spec, keyed by ref
        assert "shimsecret" not in str(spec)
        assert spec["models"][0]["key_ref"] in api_keys and api_keys[spec["models"][0]["key_ref"]] == "shimsecret"
        assert oauth_blobs["SUB_A1"] == {"t": 1}
        # stable key_ref: first api_key model gets POOL_KEY_0 regardless of position
        assert spec["models"][0]["key_ref"] == "POOL_KEY_0"
        # auto-enable: 1 api_key + 1 subscription account -> enabled
        assert compute_auto_enable(pool) is True

    def test_on_update_enqueues_sync_when_enabled(self):
        pool = self._make_test_pool()
        pool.enabled = 1
        with patch("jarvis.admin_client.post_update_llm_pool") as mock_push:
            pool.on_update()
        # auto_enabled computed and set
        assert pool.auto_enabled == 1
        # sync was triggered (inline in test mode)
        mock_push.assert_called_once()
        call_kwargs = mock_push.call_args[1]
        assert call_kwargs["spec"]["routing_mode"] == "dynamic"
        assert "shimsecret" not in str(call_kwargs["spec"])
        assert call_kwargs["api_keys"]["POOL_KEY_0"] == "shimsecret"
        assert call_kwargs["oauth_blobs"]["SUB_A1"] == {"t": 1}

    # ------------------------------------------------------------------
    # E2E validation tests: build_pool_payload -> PoolSpec -> validate
    # ------------------------------------------------------------------

    def _make_dynamic_pool_both_tiers(self):
        """Pool with 1 cheap + 1 strong api_key model — should stay dynamic."""
        pool = frappe.get_single("Jarvis LLM Pool")
        pool.routing_mode = "dynamic"
        pool.set("models", [])
        pool.append("models", {"provider": "openai_compat", "model": "gpt-4o", "tier": "strong",
                               "credential_type": "api_key", "api_key": "sk-strong", "order": 0, "enabled": 1})
        pool.append("models", {"provider": "openai_compat", "model": "gpt-3.5-turbo", "tier": "cheap",
                               "credential_type": "api_key", "api_key": "sk-cheap", "order": 1, "enabled": 1})
        return pool

    def _make_two_strong_pool(self):
        """Pool with 2 strong api_key models — dynamic has no cheap tier, must fall back to failover."""
        pool = frappe.get_single("Jarvis LLM Pool")
        pool.routing_mode = "dynamic"
        pool.set("models", [])
        pool.append("models", {"provider": "openai_compat", "model": "gpt-4o", "tier": "strong",
                               "credential_type": "api_key", "api_key": "sk-a", "order": 0, "enabled": 1})
        pool.append("models", {"provider": "openai_compat", "model": "gpt-4-turbo", "tier": "strong",
                               "credential_type": "api_key", "api_key": "sk-b", "order": 1, "enabled": 1})
        return pool

    def test_validate_dynamic_pool_with_both_tiers(self):
        """1 cheap + 1 strong → routing_mode stays 'dynamic', classifier present, validate clean."""
        import unittest
        if not _HAS_LLM_PROXY:
            raise unittest.SkipTest("llm_proxy not installed")

        from llm_proxy.schema import PoolSpec
        from llm_proxy.validate import validate
        from jarvis.jarvis.pool_serialize import build_pool_payload

        pool = self._make_dynamic_pool_both_tiers()
        spec, _, _ = build_pool_payload(pool)

        assert spec["routing_mode"] == "dynamic", f"expected dynamic, got {spec['routing_mode']}"
        assert "classifier" in spec, "classifier key must be present for dynamic routing"

        pool_spec = PoolSpec(**spec)
        issues = validate(pool_spec)
        assert issues == [], f"Expected zero validate issues, got: {issues}"

    def test_validate_two_strong_pool_falls_back_to_failover(self):
        """2 strong models (no cheap) → routing_mode falls back to 'failover', validate clean."""
        import unittest
        if not _HAS_LLM_PROXY:
            raise unittest.SkipTest("llm_proxy not installed")

        from llm_proxy.schema import PoolSpec
        from llm_proxy.validate import validate
        from jarvis.jarvis.pool_serialize import build_pool_payload

        pool = self._make_two_strong_pool()
        spec, _, _ = build_pool_payload(pool)

        assert spec["routing_mode"] == "failover", f"expected failover fallback, got {spec['routing_mode']}"
        assert "classifier" not in spec, "classifier must NOT be emitted for failover mode"

        pool_spec = PoolSpec(**spec)
        issues = validate(pool_spec)
        assert issues == [], f"Expected zero validate issues, got: {issues}"
