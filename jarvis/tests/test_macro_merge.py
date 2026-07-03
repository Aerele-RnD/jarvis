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
	def test_stores_summary_and_keeps_steps(self):
		# The sequence stays as the editable source; the summary rides alongside
		# and (see TestMergedRun) is what run_macro executes.
		m = _mk_macro([
			{"label": "a", "prompt": "p1"},
			{"label": "b", "prompt": "p2"},
			{"label": "c", "prompt": "p3"},
		])
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Macro", m.name, force=True, ignore_permissions=True))
		r = apply_macro_merge(m.name, "Do p1, and from those results p2, then p3.")
		self.assertEqual(r["step_count"], 3)  # steps untouched
		doc = frappe.get_doc("Jarvis Macro", m.name)
		self.assertEqual(len(doc.steps), 3)
		self.assertEqual([s.prompt for s in doc.steps], ["p1", "p2", "p3"])
		self.assertIn("from those results", doc.merged_prompt)

	def test_empty_prompt_refused(self):
		m = _mk_macro([{"prompt": "p1"}, {"prompt": "p2"}])
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Macro", m.name, force=True, ignore_permissions=True))
		with self.assertRaises(frappe.ValidationError):
			apply_macro_merge(m.name, "   ")

	def test_clear_macro_merge(self):
		m = _mk_macro([{"prompt": "p1"}, {"prompt": "p2"}])
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Macro", m.name, force=True, ignore_permissions=True))
		apply_macro_merge(m.name, "the summary")
		from jarvis.chat.macros_api import clear_macro_merge
		clear_macro_merge(m.name)
		self.assertEqual(frappe.db.get_value("Jarvis Macro", m.name, "merged_prompt") or "", "")

	def test_update_steps_clears_stale_summary(self):
		from jarvis.chat.macros_api import get_macro, update_macro
		m = _mk_macro([{"prompt": "p1"}, {"prompt": "p2"}])
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Macro", m.name, force=True, ignore_permissions=True))
		apply_macro_merge(m.name, "the summary")
		# steps replaced without a merged_prompt in the same call → summary is stale → cleared
		update_macro(m.name, steps=frappe.as_json([{"prompt": "p1 changed"}, {"prompt": "p2"}]))
		self.assertEqual(get_macro(m.name)["merged_prompt"], "")
		# but sending merged_prompt alongside keeps/sets it
		update_macro(m.name, steps=frappe.as_json([{"prompt": "p1"}, {"prompt": "p2"}]),
					 merged_prompt="edited summary")
		self.assertEqual(get_macro(m.name)["merged_prompt"], "edited summary")


class TestMergedRun(FrappeTestCase):
	def test_run_macro_uses_summary_as_single_turn(self):
		from jarvis.chat import macros
		m = _mk_macro([{"prompt": "p1"}, {"prompt": "p2"}, {"prompt": "p3"}])
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Macro", m.name, force=True, ignore_permissions=True))
		apply_macro_merge(m.name, "One prompt to rule them all.")
		with patch("jarvis.chat.api._enqueue_turn") as enq:
			r = macros.run_macro(m.name)
		run_name = r["data"]["macro_run"]
		conv = r["data"]["conversation"]
		self.addCleanup(lambda: (
			frappe.delete_doc("Jarvis Macro Run", run_name, force=True, ignore_permissions=True),
			frappe.db.delete("Jarvis Chat Message", {"conversation": conv}),
			frappe.delete_doc("Jarvis Conversation", conv, force=True, ignore_permissions=True),
		))
		enq.assert_called_once()  # ONE turn, not three
		self.assertTrue(enq.call_args[0][1].startswith("One prompt to rule them all."))
		run = frappe.get_doc("Jarvis Macro Run", run_name)
		self.assertEqual(run.total_steps, 1)
		self.assertEqual(run.current_step, 1)

	def test_run_macro_without_summary_chains_steps(self):
		from jarvis.chat import macros
		m = _mk_macro([{"prompt": "p1"}, {"prompt": "p2"}])
		self.addCleanup(lambda: frappe.delete_doc("Jarvis Macro", m.name, force=True, ignore_permissions=True))
		with patch("jarvis.chat.api._enqueue_turn") as enq:
			r = macros.run_macro(m.name)
		run_name = r["data"]["macro_run"]
		conv = r["data"]["conversation"]
		self.addCleanup(lambda: (
			frappe.delete_doc("Jarvis Macro Run", run_name, force=True, ignore_permissions=True),
			frappe.db.delete("Jarvis Chat Message", {"conversation": conv}),
			frappe.delete_doc("Jarvis Conversation", conv, force=True, ignore_permissions=True),
		))
		enq.assert_called_once()  # step 1 enqueued; the chain advances per turn
		self.assertTrue(enq.call_args[0][1].startswith("p1"))
		self.assertEqual(frappe.get_doc("Jarvis Macro Run", run_name).total_steps, 2)


class TestDiscardMacroMerge(FrappeTestCase):
	def test_deletes_conversation_and_messages(self):
		conv = _mk_conv(assistant=MERGE_BLOCK)
		discard_macro_merge(conv)
		self.assertFalse(frappe.db.exists("Jarvis Conversation", conv))
		self.assertEqual(frappe.db.count("Jarvis Chat Message", {"conversation": conv}), 0)
