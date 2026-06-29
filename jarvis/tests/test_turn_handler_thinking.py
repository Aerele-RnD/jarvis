from frappe.tests.utils import FrappeTestCase

from jarvis.chat.turn_handler import _thinking_prefix


class TestThinkingPrefix(FrappeTestCase):
    def test_levels_emit_directive(self):
        self.assertEqual(_thinking_prefix("low"), "/think low\n")
        self.assertEqual(_thinking_prefix("MEDIUM"), "/think medium\n")
        self.assertEqual(_thinking_prefix("high"), "/think high\n")

    def test_empty_or_invalid_emits_nothing(self):
        self.assertEqual(_thinking_prefix(""), "")
        self.assertEqual(_thinking_prefix(None), "")
        self.assertEqual(_thinking_prefix("ultra"), "")
