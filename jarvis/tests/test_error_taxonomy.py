"""Pure classification tests; no site, credentials, or running services needed."""

import json
import unittest
from pathlib import Path

from jarvis.chat.error_taxonomy import classify_error_text


class TestErrorTaxonomy(unittest.TestCase):
	def test_error_cases(self):
		cases = json.loads((Path(__file__).parent / "fixtures/turn_errors.json").read_text())
		for case in cases:
			with self.subTest(error=case["error"]):
				self.assertEqual(classify_error_text(case["error"]), case["code"])

	def test_structured_error(self):
		self.assertEqual(classify_error_text({"error": {"type": "overloaded_error"}}), "service-unavailable")
