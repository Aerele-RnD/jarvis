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
        self.assertEqual(depends_on, "eval:doc.credential_type=='api_key'",
                         "provider field depends_on must be exactly eval:doc.credential_type=='api_key'")

    def test_pool_model_base_url_has_depends_on_credential_type(self):
        """Pool Model 'base_url' field must have depends_on gating on credential_type=='api_key'."""
        self.assertIn("base_url", self.pool_model_fields)
        depends_on = self.pool_model_fields["base_url"].depends_on or ""
        self.assertEqual(depends_on, "eval:doc.credential_type=='api_key'",
                         "base_url field depends_on must be exactly eval:doc.credential_type=='api_key'")

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


# ---------------------------------------------------------------------------
# Task 2: pool_serialize re-sourced from settings.models + hygiene tests
# ---------------------------------------------------------------------------

def _make_settings_with_models(models_rows):
    """Build a minimal in-memory settings-like object without saving to DB.

    Uses frappe._dict so that _get_password adapter works (hasattr(doc, 'get') path).
    models_rows is a list of frappe._dict; accounts inside subscription models
    are also frappe._dict objects.
    """
    settings = frappe._dict(
        models=models_rows,
        preset=None,
        routing_mode="dynamic",
    )
    return settings


def _api_key_model(**kwargs):
    defaults = frappe._dict(
        model="gpt-4o",
        tier="strong",
        order=0,
        enabled=1,
        credential_type="api_key",
        api_key="sk-test-key",
        provider="openai_compat",
        base_url="https://api.openai.com",
        rotation=None,
        accounts=[],
    )
    defaults.update(kwargs)
    return defaults


def _subscription_model(**kwargs):
    defaults = frappe._dict(
        model="gpt-5.5",
        tier="cheap",
        order=1,
        enabled=1,
        credential_type="subscription",
        api_key=None,
        provider="",
        base_url="",
        rotation="round_robin",
        accounts=[],
    )
    defaults.update(kwargs)
    return defaults


def _account(upstream="openai", account_ref="ACC_001", label="test@example.com", oauth_blob='{"token":"abc"}'):
    return frappe._dict(
        upstream=upstream,
        account_ref=account_ref,
        label=label,
        oauth_blob=oauth_blob,
    )


class TestPoolSerializeFromSettings(FrappeTestCase):
    """Task 2: Direct-call tests for build_pool_payload / validate_models / compute_proxy_active."""

    # ------------------------------------------------------------------ #
    # Imports
    # ------------------------------------------------------------------ #

    def _imports(self):
        from jarvis.jarvis.pool_serialize import (
            build_pool_payload,
            validate_models,
            compute_proxy_active,
        )
        return build_pool_payload, validate_models, compute_proxy_active

    # ------------------------------------------------------------------ #
    # (a) Secrets out of spec
    # ------------------------------------------------------------------ #

    def test_secrets_not_in_spec(self):
        """API key values must NOT appear in the serialized spec dict."""
        build_pool_payload, _, _ = self._imports()
        m = _api_key_model(api_key="super-secret-key-xyz")
        settings = _make_settings_with_models([m])
        spec, api_keys, _ = build_pool_payload(settings)
        # secret must not appear anywhere in spec
        self.assertNotIn("super-secret-key-xyz", str(spec))
        # secret must be in api_keys under the key_ref
        self.assertTrue(any(v == "super-secret-key-xyz" for v in api_keys.values()))

    # ------------------------------------------------------------------ #
    # (b) Subscription entry omits provider/base_url
    # ------------------------------------------------------------------ #

    def test_subscription_model_omits_provider_and_base_url(self):
        """Subscription models must NOT emit provider or base_url in the spec."""
        build_pool_payload, _, _ = self._imports()
        acc = _account()
        m = _subscription_model(accounts=[acc], provider="openai_compat", base_url="https://api.openai.com")
        settings = _make_settings_with_models([m])
        spec, _, _ = build_pool_payload(settings)
        entry = spec["models"][0]
        self.assertNotIn("provider", entry, "subscription entry must not emit provider")
        self.assertNotIn("base_url", entry, "subscription entry must not emit base_url")

    # ------------------------------------------------------------------ #
    # (c) Mixed upstream across accounts → validate_models error
    # ------------------------------------------------------------------ #

    def test_mixed_upstream_across_accounts_is_a_validate_error(self):
        """Accounts with different upstreams in one subscription model → validate_models error."""
        _, validate_models, _ = self._imports()
        acc1 = _account(upstream="openai", account_ref="ACC_001")
        acc2 = _account(upstream="google", account_ref="ACC_002")
        m = _subscription_model(accounts=[acc1, acc2])
        settings = _make_settings_with_models([m])
        errors = validate_models(settings)
        self.assertTrue(
            any("upstream" in e.lower() or "mixed" in e.lower() or "consistent" in e.lower() for e in errors),
            f"Expected upstream consistency error, got: {errors}"
        )

    # ------------------------------------------------------------------ #
    # (d) Duplicate account_ref → validate_models error
    # ------------------------------------------------------------------ #

    def test_duplicate_account_ref_is_a_validate_error(self):
        """Same account_ref used in two different models → validate_models error."""
        _, validate_models, _ = self._imports()
        acc1 = _account(upstream="openai", account_ref="DUPE_REF")
        acc2 = _account(upstream="openai", account_ref="DUPE_REF")
        m1 = _subscription_model(accounts=[acc1], model="gpt-5.5", order=0)
        m2 = _subscription_model(accounts=[acc2], model="gpt-4o-mini", tier="strong", order=1)
        settings = _make_settings_with_models([m1, m2])
        errors = validate_models(settings)
        self.assertTrue(
            any("duplicate" in e.lower() or "account_ref" in e.lower() for e in errors),
            f"Expected duplicate account_ref error, got: {errors}"
        )

    # ------------------------------------------------------------------ #
    # (e) Blank api_key on enabled api_key model → validate_models error
    # ------------------------------------------------------------------ #

    def test_blank_api_key_on_enabled_model_is_a_validate_error(self):
        """Enabled api_key model with empty key → validate_models error (no dangling key_ref)."""
        _, validate_models, _ = self._imports()
        m = _api_key_model(api_key="", enabled=1)
        settings = _make_settings_with_models([m])
        errors = validate_models(settings)
        self.assertTrue(
            any("api_key" in e.lower() or "key" in e.lower() or "blank" in e.lower() for e in errors),
            f"Expected blank api_key error, got: {errors}"
        )

    # ------------------------------------------------------------------ #
    # (f) Empty subscription accounts → validate_models error
    # ------------------------------------------------------------------ #

    def test_empty_accounts_on_enabled_subscription_model_is_a_validate_error(self):
        """Enabled subscription model with no accounts → validate_models error."""
        _, validate_models, _ = self._imports()
        m = _subscription_model(accounts=[], enabled=1)
        settings = _make_settings_with_models([m])
        errors = validate_models(settings)
        self.assertTrue(
            any("account" in e.lower() or "empty" in e.lower() for e in errors),
            f"Expected empty accounts error, got: {errors}"
        )

    # ------------------------------------------------------------------ #
    # (g) Malformed oauth_blob → validate_models error STRING (no raise)
    # ------------------------------------------------------------------ #

    def test_malformed_oauth_blob_returns_error_string_not_raise(self):
        """Malformed JSON in oauth_blob must produce a validate_models error string — NOT raise."""
        build_pool_payload, validate_models, _ = self._imports()
        acc = _account(oauth_blob="{not valid json!!!")
        m = _subscription_model(accounts=[acc])
        settings = _make_settings_with_models([m])

        # validate_models must NOT raise — must return list with an error
        try:
            errors = validate_models(settings)
        except Exception as exc:
            self.fail(f"validate_models raised an exception on malformed oauth_blob: {exc}")
        self.assertTrue(
            any("oauth" in e.lower() or "json" in e.lower() or "blob" in e.lower() or "malformed" in e.lower() for e in errors),
            f"Expected malformed oauth_blob error string, got: {errors}"
        )

        # build_pool_payload must also NOT raise
        try:
            build_pool_payload(settings)
        except Exception as exc:
            self.fail(f"build_pool_payload raised on malformed oauth_blob: {exc}")

    # ------------------------------------------------------------------ #
    # (h) compute_proxy_active
    # ------------------------------------------------------------------ #

    def test_compute_proxy_active_true_when_two_enabled_models(self):
        """compute_proxy_active is True when ≥2 models are enabled."""
        _, _, compute_proxy_active = self._imports()
        m1 = _api_key_model(enabled=1)
        m2 = _api_key_model(model="gpt-4-turbo", enabled=1, order=1)
        settings = _make_settings_with_models([m1, m2])
        self.assertTrue(compute_proxy_active(settings))

    def test_compute_proxy_active_true_when_preset_set(self):
        """compute_proxy_active is True when preset is set (even with only 1 model)."""
        _, _, compute_proxy_active = self._imports()
        m = _api_key_model(enabled=1)
        settings = _make_settings_with_models([m])
        settings.preset = "Cost-saver"
        self.assertTrue(compute_proxy_active(settings))

    def test_compute_proxy_active_false_when_one_model_no_preset(self):
        """compute_proxy_active is False for exactly 1 enabled model and no preset."""
        _, _, compute_proxy_active = self._imports()
        m = _api_key_model(enabled=1)
        settings = _make_settings_with_models([m])
        settings.preset = None
        self.assertFalse(compute_proxy_active(settings))

    # ------------------------------------------------------------------ #
    # No dangling key_ref: build_pool_payload only emits key_ref+api_keys together
    # ------------------------------------------------------------------ #

    def test_no_dangling_key_ref_when_api_key_is_blank(self):
        """A model with blank api_key must not emit a key_ref pointing to nothing."""
        build_pool_payload, _, _ = self._imports()
        m = _api_key_model(api_key="", enabled=1)
        settings = _make_settings_with_models([m])
        spec, api_keys, _ = build_pool_payload(settings)
        # The blank-key model must not have key_ref at all
        for entry in spec.get("models", []):
            self.assertNotIn("key_ref", entry,
                             "blank api_key model must not emit key_ref in spec")

    # ------------------------------------------------------------------ #
    # anthropic upstream → validate_models error
    # ------------------------------------------------------------------ #

    def test_anthropic_upstream_in_subscription_is_a_validate_error(self):
        """Subscription account with upstream='anthropic' → validate_models error (ToS)."""
        _, validate_models, _ = self._imports()
        acc = _account(upstream="anthropic")
        m = _subscription_model(accounts=[acc])
        settings = _make_settings_with_models([m])
        errors = validate_models(settings)
        self.assertTrue(
            any("anthropic" in e.lower() or "tos" in e.lower() or "upstream" in e.lower() for e in errors),
            f"Expected anthropic upstream ToS error, got: {errors}"
        )

    # ------------------------------------------------------------------ #
    # (i) Blank account_ref on subscription account
    # ------------------------------------------------------------------ #

    def test_blank_account_ref_on_subscription_is_a_validate_error(self):
        """Enabled subscription account with blank account_ref → validate_models error."""
        _, validate_models, _ = self._imports()
        acc = _account(account_ref="")  # blank account_ref
        m = _subscription_model(accounts=[acc])
        settings = _make_settings_with_models([m])
        errors = validate_models(settings)
        self.assertTrue(
            any("account_ref" in e.lower() or "missing" in e.lower() for e in errors),
            f"Expected blank account_ref error, got: {errors}"
        )

    def test_blank_account_ref_does_not_write_empty_string_oauth_key(self):
        """Enabled subscription account with blank account_ref must not produce oauth_blobs['']."""
        build_pool_payload, _, _ = self._imports()
        acc = _account(account_ref="", oauth_blob='{"token":"secret"}')
        m = _subscription_model(accounts=[acc])
        settings = _make_settings_with_models([m])
        _, _, oauth_blobs = build_pool_payload(settings)
        self.assertNotIn("", oauth_blobs,
                         "blank account_ref must NOT produce an empty-string key in oauth_blobs")


# ---------------------------------------------------------------------------
# Task 3: E2E serialize → llm_proxy.validate tests
# (ported from test_jarvis_llm_pool.py — re-sourced from Jarvis Settings)
# ---------------------------------------------------------------------------

try:
    import llm_proxy as _llm_proxy_mod
    _HAS_LLM_PROXY = True
except ImportError:
    _HAS_LLM_PROXY = False


class TestPoolSerializeE2E(FrappeTestCase):
    """E2E tests: build_pool_payload(settings) → PoolSpec → llm_proxy.validate → zero issues."""

    def _imports(self):
        from jarvis.jarvis.pool_serialize import build_pool_payload
        return build_pool_payload

    def _make_settings_dynamic_both_tiers(self):
        """Settings with 1 strong + 1 cheap api_key model — routing_mode must stay dynamic."""
        strong = _api_key_model(
            model="gpt-4o", tier="strong", order=0, enabled=1,
            api_key="sk-strong", provider="openai_compat",
            base_url="https://api.openai.com",
        )
        cheap = _api_key_model(
            model="gpt-3.5-turbo", tier="cheap", order=1, enabled=1,
            api_key="sk-cheap", provider="openai_compat",
            base_url="https://api.openai.com",
        )
        settings = _make_settings_with_models([strong, cheap])
        return settings

    def _make_settings_two_strong(self):
        """Settings with 2 strong api_key models — no cheap tier → routing_mode must fall back to failover."""
        m1 = _api_key_model(
            model="gpt-4o", tier="strong", order=0, enabled=1,
            api_key="sk-a", provider="openai_compat",
            base_url="https://api.openai.com",
        )
        m2 = _api_key_model(
            model="gpt-4-turbo", tier="strong", order=1, enabled=1,
            api_key="sk-b", provider="openai_compat",
            base_url="https://api.openai.com",
        )
        settings = _make_settings_with_models([m1, m2])
        return settings

    def test_e2e_dynamic_pool_with_both_tiers_validates_clean(self):
        """1 cheap + 1 strong → routing_mode stays 'dynamic', classifier present, validate() clean."""
        import unittest
        if not _HAS_LLM_PROXY:
            raise unittest.SkipTest("llm_proxy not installed")

        from llm_proxy.schema import PoolSpec
        from llm_proxy.validate import validate

        build_pool_payload = self._imports()
        settings = self._make_settings_dynamic_both_tiers()
        spec, _, _ = build_pool_payload(settings)

        self.assertEqual(spec["routing_mode"], "dynamic",
                         f"expected dynamic routing_mode, got {spec['routing_mode']}")
        self.assertIn("classifier", spec,
                      "classifier key must be present for dynamic routing")

        pool_spec = PoolSpec(**spec)
        issues = validate(pool_spec)
        self.assertEqual(issues, [], f"Expected zero validate issues, got: {issues}")

    def test_e2e_two_strong_pool_falls_back_to_failover_and_validates_clean(self):
        """2 strong models (no cheap) → routing_mode falls back to 'failover', validate() clean."""
        import unittest
        if not _HAS_LLM_PROXY:
            raise unittest.SkipTest("llm_proxy not installed")

        from llm_proxy.schema import PoolSpec
        from llm_proxy.validate import validate

        build_pool_payload = self._imports()
        settings = self._make_settings_two_strong()
        spec, _, _ = build_pool_payload(settings)

        self.assertEqual(spec["routing_mode"], "failover",
                         f"expected failover fallback, got {spec['routing_mode']}")
        self.assertNotIn("classifier", spec,
                         "classifier must NOT be emitted for failover mode")

        pool_spec = PoolSpec(**spec)
        issues = validate(pool_spec)
        self.assertEqual(issues, [], f"Expected zero validate issues, got: {issues}")
