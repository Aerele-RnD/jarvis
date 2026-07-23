from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import admin_client
from jarvis.exceptions import AdminUnreachableError

_PAYLOAD = [
	{
		"provider_id": "openai",
		"label": "OpenAI",
		"default_base_url": "https://api.openai.com/v1",
		"renderer_id": "openai-codex",
		"auth_profile_id": "openai",
		"supports_api_key": True,
		"supports_subscription": True,
		"needs_base_url": False,
		"is_local": False,
		"models": [
			{
				"model_id": "gpt-5.5",
				"label": "gpt-5.5",
				"tier": "subscription",
				"is_default": True,
				"sort_order": 0,
			}
		],
	}
]


class TestGetModelCatalog(FrappeTestCase):
	def setUp(self):
		frappe.cache().delete_value(admin_client._MODEL_CATALOG_CACHE_KEY)
		frappe.cache().delete_value(admin_client._MODEL_CATALOG_FAIL_KEY)

	def test_fetches_and_caches_admin_catalog(self):
		with patch.object(admin_client, "_post_guest", return_value=_PAYLOAD) as gp:
			out = admin_client.get_model_catalog()
		self.assertEqual(out, _PAYLOAD)
		gp.assert_called_once()
		self.assertIn("get_provider_catalog", gp.call_args.kwargs.get("path", ""))
		with patch.object(admin_client, "_post_guest", side_effect=AssertionError("must use cache")):
			self.assertEqual(admin_client.get_model_catalog(), _PAYLOAD)

	def test_cache_hit_short_circuits_network(self):
		frappe.cache().set_value(
			admin_client._MODEL_CATALOG_CACHE_KEY,
			_PAYLOAD,
			expires_in_sec=admin_client._MODEL_CATALOG_TTL_S,
		)
		with patch.object(admin_client, "_post_guest") as m:
			result = admin_client.get_model_catalog()
		self.assertEqual(result, _PAYLOAD)
		m.assert_not_called()

	def test_falls_back_to_bundled_when_admin_down_and_cache_empty(self):
		from jarvis._model_catalog import BUNDLED_MODEL_CATALOG

		with patch.object(admin_client, "_post_guest", side_effect=AdminUnreachableError("down")):
			out = admin_client.get_model_catalog()
		self.assertEqual(out, BUNDLED_MODEL_CATALOG)
		self.assertTrue(all("provider_id" in e and "models" in e for e in out))

	def test_never_raises_on_any_exception(self):
		from jarvis._model_catalog import BUNDLED_MODEL_CATALOG

		with patch.object(admin_client, "_post_guest", side_effect=ValueError("scheme-less url")):
			out = admin_client.get_model_catalog()
		self.assertEqual(out, BUNDLED_MODEL_CATALOG)

	def test_uses_a_short_timeout_not_the_150s_default(self):
		# R3: this runs inside send_message. DEFAULT_TIMEOUT_S is 150.
		with patch.object(admin_client, "_post_guest", return_value=_PAYLOAD) as gp:
			admin_client.get_model_catalog()
		self.assertLessEqual(gp.call_args.kwargs.get("timeout_s", 150), 10)

	def test_a_failure_is_cached_so_the_hot_path_stops_retrying(self):
		# R3: without negative caching a hanging admin costs EVERY chat send a
		# full timeout. One failure must suppress the next call entirely.
		frappe.cache().delete_value(admin_client._MODEL_CATALOG_FAIL_KEY)
		with patch.object(admin_client, "_post_guest", side_effect=AdminUnreachableError("down")):
			admin_client.get_model_catalog()
		with patch.object(admin_client, "_post_guest", side_effect=AssertionError("must not retry")) as gp:
			out = admin_client.get_model_catalog()
		gp.assert_not_called()
		from jarvis._model_catalog import BUNDLED_MODEL_CATALOG

		self.assertEqual(out, BUNDLED_MODEL_CATALOG)

	def test_an_empty_payload_also_trips_the_failure_marker(self):
		frappe.cache().delete_value(admin_client._MODEL_CATALOG_FAIL_KEY)
		with patch.object(admin_client, "_post_guest", return_value=[]):
			admin_client.get_model_catalog()
		self.assertTrue(frappe.cache().get_value(admin_client._MODEL_CATALOG_FAIL_KEY))


class TestBundledCatalogMirrorsAdminSeed(FrappeTestCase):
	def test_bundle_covers_every_provider_and_model(self):
		# R4: the bundle IS what CI and every outage sees. If it drifts from the
		# admin seed, tests pass locally (admin reachable) and fail on CI.
		from jarvis._model_catalog import BUNDLED_MODEL_CATALOG

		self.assertEqual(len(BUNDLED_MODEL_CATALOG), 15)
		by_id = {p["provider_id"]: p for p in BUNDLED_MODEL_CATALOG}
		# Spot-check the entries the older trimmed draft dropped.
		for pid in ("mistral", "groq", "together", "deepseek", "openrouter", "zai", "zai_coding"):
			self.assertIn(pid, by_id, f"bundle is missing {pid}")
		self.assertEqual(by_id["moonshot"]["subscription_label"], "Kimi (Moonshot)")
		self.assertEqual(by_id["google"]["catalog_id"], "gemini")

	def test_bundle_preserves_the_full_subscription_lists(self):
		# test_subscription_models.py:31 asserts every active gemini model coerces.
		from jarvis._model_catalog import BUNDLED_MODEL_CATALOG

		g = next(p for p in BUNDLED_MODEL_CATALOG if p["provider_id"] == "google")
		subs = [m["model_id"] for m in g["models"] if m["tier"] == "subscription"]
		self.assertEqual(subs, ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-3.1-flash"])
