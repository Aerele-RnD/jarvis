"""Tests for jarvis._subscription_models - the subscription model catalogue."""
import json
import unittest

from jarvis import _subscription_models as cat
from jarvis.oauth.api import _coerce_subscription_model

GEMINI = "Google Gemini"
EXPECTED_GEMINI = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-3.1-flash",
]


class TestSubscriptionCatalogue(unittest.TestCase):
    def test_gemini_list_is_active_set(self):
        self.assertEqual(cat.SUBSCRIPTION_MODELS[GEMINI], EXPECTED_GEMINI)

    def test_gemini_default_is_in_list(self):
        self.assertEqual(cat.DEFAULT_MODEL[GEMINI], "gemini-2.5-pro")
        self.assertIn(cat.DEFAULT_MODEL[GEMINI], cat.SUBSCRIPTION_MODELS[GEMINI])

    def test_catalogue_values_are_json_serializable_lists(self):
        json.dumps(cat.SUBSCRIPTION_MODELS)  # must not raise
        for value in cat.SUBSCRIPTION_MODELS.values():
            self.assertIsInstance(value, list)

    def test_coerce_accepts_every_active_gemini_model(self):
        for model in EXPECTED_GEMINI:
            self.assertEqual(_coerce_subscription_model(GEMINI, model), model)

    def test_coerce_falls_back_to_default_for_bogus_and_empty(self):
        self.assertEqual(_coerce_subscription_model(GEMINI, "nope"), "gemini-2.5-pro")
        self.assertEqual(_coerce_subscription_model(GEMINI, ""), "gemini-2.5-pro")

    def test_openai_entry_unchanged(self):
        self.assertEqual(cat.SUBSCRIPTION_MODELS["OpenAI"],
                         ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"])
        self.assertEqual(cat.DEFAULT_MODEL["OpenAI"], "gpt-5.5")
