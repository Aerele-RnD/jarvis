"""Tests for the macro-merge surface (summarize a step sequence into one prompt).

The LLM summarize turn itself is exercised by the live smoke; these tests
cover the deterministic plumbing: enqueue + throwaway conversation, the poll
state machine parsing the jarvis-macro-merge block, and the apply that
collapses the steps (skills union, first non-empty overrides), all
owner-gated.
"""
from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.macros_api import (
	apply_macro_merge,
	discard_macro_merge,
	get_macro_merge,
	summarize_macro,
)

MERGE_BLOCK = (
	"Here you go:\n\n```jarvis-macro-merge\n"
	'{"mergeable": true, "reason": "2 uses 1", '
	'"merged_prompt": "1) Analytics.\\n2) Using the results of (1), find the top debtor.", '
	'"dependencies": [{"step": 2, "uses": [1]}]}\n```'
)


def _mk_macro(steps):
	doc = frappe.get_doc({
		"doctype": "Jarvis Macro",
		"macro_name": f"merge-test-{frappe.generate_hash(length=6)}",
		"enabled": 1,
		"steps": steps,
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def _mk_conv(assistant=None, streaming=0, error=""):
	conv = frappe.get_doc({"doctype": "Jarvis Conversation", "title": "merge test"})
	conv.flags.ignore_permissions = True
	conv.insert()
	if assistant is not None:
		frappe.get_doc({
			"doctype": "Jarvis Chat Message", "conversation": conv.name, "seq": 2,
			"role": "assistant", "content": assistant, "streaming": streaming,
			"error": error,
		}).insert(ignore_permissions=True)
	return conv.name


class TestSummarizeMacro(FrappeTestCase):
	def test_enqueues_one_turn_with_steps_and_skill(self):
		m = _mk_macro([
			{"label": "a", "prompt": "Sales analytics for last quarter"},
			{"label": "b", "prompt": "Find the highest outstanding customer"},
		])
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Macro", m.name, force=True, ignore_permissions=True))
		with patch("jarvis.chat.api._enqueue_turn") as enq:
			r = summarize_macro(m.name)
		self.assertTrue(r["ok"])
		conv = r["conversation"]
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Conversation", conv, force=True, ignore_permissions=True))
		# one turn, into the returned conversation, steps JSON + skill invocation in the prompt
		enq.assert_called_once()
		args, kwargs = enq.call_args
		self.assertEqual(args[0], conv)
		self.assertIn("Sales analytics for last quarter", args[1])
		self.assertIn("/macro-merge", args[1])
		# throwaway conversation is hidden from the sidebar
		self.assertEqual(frappe.db.get_value("Jarvis Conversation", conv, "status"), "Archived")

	def test_rejects_single_step_macro(self):
		m = _mk_macro([{"label": "only", "prompt": "one thing"}])
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Macro", m.name, force=True, ignore_permissions=True))
		with self.assertRaises(frappe.ValidationError):
			summarize_macro(m.name)


class TestGetMacroMerge(FrappeTestCase):
	def _cleanup_conv(self, conv):
		self.addCleanup(lambda: (
			frappe.db.delete("Jarvis Chat Message", {"conversation": conv}),
			frappe.delete_doc("Jarvis Conversation", conv, force=True, ignore_permissions=True),
		))

	def test_pending_when_no_reply(self):
		conv = _mk_conv(assistant=None)
		self._cleanup_conv(conv)
		self.assertEqual(get_macro_merge(conv)["status"], "pending")

	def test_pending_while_streaming(self):
		conv = _mk_conv(assistant="partial", streaming=1)
		self._cleanup_conv(conv)
		self.assertEqual(get_macro_merge(conv)["status"], "pending")

	def test_error_from_turn_error(self):
		conv = _mk_conv(assistant="", error="quota exceeded")
		self._cleanup_conv(conv)
		r = get_macro_merge(conv)
		self.assertEqual(r["status"], "error")
		self.assertIn("quota", r["error"])

	def test_error_when_no_block(self):
		conv = _mk_conv(assistant="I could not do that.")
		self._cleanup_conv(conv)
		self.assertEqual(get_macro_merge(conv)["status"], "error")

	def test_ready_parses_block(self):
		conv = _mk_conv(assistant=MERGE_BLOCK)
		self._cleanup_conv(conv)
		r = get_macro_merge(conv)
		self.assertEqual(r["status"], "ready")
		self.assertTrue(r["merge"]["mergeable"])
		self.assertIn("Using the results of (1)", r["merge"]["merged_prompt"])
		self.assertEqual(r["merge"]["dependencies"], [{"step": 2, "uses": [1]}])

	def test_ownership_enforced(self):
		conv = _mk_conv(assistant=MERGE_BLOCK)
		self._cleanup_conv(conv)
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				get_macro_merge(conv)
		finally:
			frappe.set_user("Administrator")


class TestApplyMacroMerge(FrappeTestCase):
	def test_replaces_steps_with_one_merged_step(self):
		m = _mk_macro([
			{"label": "a", "prompt": "p1", "skills": frappe.as_json(["SK-A", "SK-B"]),
			 "model_override": "", "thinking_override": "high"},
			{"label": "b", "prompt": "p2", "skills": frappe.as_json(["SK-B", "SK-C"]),
			 "model_override": "gpt-5.5", "thinking_override": ""},
			{"label": "c", "prompt": "p3"},
		])
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Macro", m.name, force=True, ignore_permissions=True))
		r = apply_macro_merge(m.name, "1) p1. 2) Using the results of (1), p2. 3) p3.")
		self.assertEqual(r["step_count"], 1)
		doc = frappe.get_doc("Jarvis Macro", m.name)
		self.assertEqual(len(doc.steps), 1)
		s = doc.steps[0]
		self.assertEqual(s.label, "Merged")
		self.assertIn("Using the results of (1)", s.prompt)
		self.assertEqual(frappe.parse_json(s.skills), ["SK-A", "SK-B", "SK-C"])  # union, order kept
		self.assertEqual(s.model_override, "gpt-5.5")   # first non-empty
		self.assertEqual(s.thinking_override, "high")   # first non-empty

	def test_empty_prompt_refused(self):
		m = _mk_macro([{"prompt": "p1"}, {"prompt": "p2"}])
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Macro", m.name, force=True, ignore_permissions=True))
		with self.assertRaises(frappe.ValidationError):
			apply_macro_merge(m.name, "   ")


class TestDiscardMacroMerge(FrappeTestCase):
	def test_deletes_conversation_and_messages(self):
		conv = _mk_conv(assistant=MERGE_BLOCK)
		discard_macro_merge(conv)
		self.assertFalse(frappe.db.exists("Jarvis Conversation", conv))
		self.assertEqual(frappe.db.count("Jarvis Chat Message", {"conversation": conv}), 0)
