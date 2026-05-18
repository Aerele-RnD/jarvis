"""Tests for jarvis.chat.api — whitelisted endpoints.

These tests run as a **dedicated test user** (``TEST_USER``) so they never
touch Administrator's data. Running the suite against a dev site that has
real chat history previously wiped that history; the fixture user keeps
test cleanups scoped to disposable rows.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.api import (
	archive_conversation,
	create_conversation,
	create_or_focus_empty,
	get_conversation,
	list_conversations,
	retry_message,
)

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"
TEST_USER = "jarvis-test@example.com"


def _ensure_test_user(user: str = TEST_USER) -> None:
	"""Create the fixture user if missing; idempotent."""
	if frappe.db.exists("User", user):
		return
	doc = frappe.get_doc({
		"doctype": "User",
		"email": user,
		"first_name": "Jarvis",
		"last_name": "Test",
		"enabled": 1,
		"send_welcome_email": 0,
		"user_type": "System User",
	})
	doc.insert(ignore_permissions=True)
	# Grant System Manager so the test user can dispatch every tool path.
	doc.add_roles("System Manager")
	frappe.db.commit()


def _cleanup_user_conversations(user: str = TEST_USER) -> None:
	"""Delete all conversations owned by `user` (and their messages).

	Defaults to the test fixture user — callers should NOT pass
	``Administrator`` here; doing so wipes real chat history on the dev site.
	"""
	names = frappe.get_all(CONV, filters={"owner": user}, pluck="name")
	for name in names:
		for child in frappe.get_all(MSG, filters={"conversation": name}, pluck="name"):
			frappe.delete_doc(MSG, child, ignore_permissions=True, force=True)
		frappe.delete_doc(CONV, name, ignore_permissions=True, force=True)
	frappe.db.commit()


class _ChatTestCase(FrappeTestCase):
	"""Base class that switches to the fixture user for the test lifetime
	and restores the original session user on teardown.
	"""

	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()

	def tearDown(self):
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)


class TestCreateConversation(_ChatTestCase):
	def test_creates_a_row_owned_by_current_user(self):
		name = create_conversation()
		doc = frappe.get_doc(CONV, name)
		self.assertEqual(doc.owner, TEST_USER)
		self.assertEqual(doc.status, "active")
		self.assertIsNotNone(doc.last_active_at)

	def test_title_defaults_to_new_chat(self):
		name = create_conversation()
		doc = frappe.get_doc(CONV, name)
		self.assertEqual(doc.title, "New chat")


class TestListConversations(_ChatTestCase):
	def test_returns_empty_when_no_conversations(self):
		result = list_conversations()
		self.assertEqual(result, [])

	def test_returns_active_conversations_for_current_user_only(self):
		a = create_conversation()
		b = create_conversation()
		result = list_conversations()
		names = {c["name"] for c in result}
		self.assertIn(a, names)
		self.assertIn(b, names)

	def test_excludes_archived_by_default(self):
		a = create_conversation()
		archive_conversation(a)
		result = list_conversations()
		names = {c["name"] for c in result}
		self.assertNotIn(a, names)

	def test_includes_message_count(self):
		a = create_conversation()
		b = create_conversation()
		# Add one message to `a` only
		frappe.get_doc({
			"doctype": MSG,
			"conversation": a,
			"seq": 1,
			"role": "user",
			"content": "hi",
		}).insert(ignore_permissions=True)
		frappe.db.commit()

		result = {c["name"]: c for c in list_conversations()}
		self.assertEqual(result[a]["message_count"], 1)
		self.assertEqual(result[b]["message_count"], 0)


class TestCreateOrFocusEmpty(_ChatTestCase):
	def test_creates_when_no_conversations_exist(self):
		name = create_or_focus_empty()
		self.assertTrue(frappe.db.exists(CONV, name))
		self.assertEqual(frappe.db.get_value(CONV, name, "owner"), TEST_USER)

	def test_returns_existing_empty_instead_of_creating(self):
		existing = create_conversation()
		returned = create_or_focus_empty()
		self.assertEqual(returned, existing)
		# Only one conversation total
		self.assertEqual(len(list_conversations()), 1)

	def test_creates_new_when_only_non_empty_exist(self):
		filled = create_conversation()
		frappe.get_doc({
			"doctype": MSG,
			"conversation": filled,
			"seq": 1,
			"role": "user",
			"content": "hi",
		}).insert(ignore_permissions=True)
		frappe.db.commit()

		returned = create_or_focus_empty()
		self.assertNotEqual(returned, filled)
		# A second conversation now exists, and it's empty
		all_names = {c["name"] for c in list_conversations()}
		self.assertIn(filled, all_names)
		self.assertIn(returned, all_names)

	def test_prefers_most_recent_empty(self):
		older = create_conversation()
		# Force older to have an earlier last_active_at
		frappe.db.set_value(CONV, older, "last_active_at", "2020-01-01 00:00:00")
		newer = create_conversation()
		returned = create_or_focus_empty()
		self.assertEqual(returned, newer)


class TestGetConversation(_ChatTestCase):
	def test_returns_conversation_with_empty_messages(self):
		name = create_conversation()
		result = get_conversation(name)
		self.assertEqual(result["conversation"]["name"], name)
		self.assertEqual(result["messages"], [])

	def test_returns_messages_in_seq_order(self):
		name = create_conversation()
		# Manually insert messages out of seq order
		for seq, role, content in [(2, "assistant", "B"), (1, "user", "A")]:
			doc = frappe.get_doc({
				"doctype": MSG,
				"conversation": name,
				"seq": seq,
				"role": role,
				"content": content,
			})
			doc.insert(ignore_permissions=True)
		frappe.db.commit()
		result = get_conversation(name)
		self.assertEqual([m["seq"] for m in result["messages"]], [1, 2])

	def test_raises_for_unknown_conversation(self):
		with self.assertRaises(frappe.DoesNotExistError):
			get_conversation("JCONV-99999")


class TestArchiveConversation(_ChatTestCase):
	def test_sets_status_to_archived(self):
		name = create_conversation()
		archive_conversation(name)
		doc = frappe.get_doc(CONV, name)
		self.assertEqual(doc.status, "archived")


from jarvis.chat.api import send_message


class TestSendMessage(_ChatTestCase):
	def setUp(self):
		super().setUp()
		self.conv = create_conversation()

	def test_rejects_when_policy_says_no(self):
		with patch(
			"jarvis.chat.api.validate_can_send",
			return_value=(False, "no credits"),
		):
			result = send_message(self.conv, "hi")
		self.assertFalse(result["ok"])
		self.assertEqual(result["reason"], "no credits")

	def test_rejects_empty_message(self):
		result = send_message(self.conv, "   ")
		self.assertFalse(result["ok"])
		self.assertIn("empty", result["reason"].lower())

	def test_rejects_unknown_conversation(self):
		with self.assertRaises(frappe.DoesNotExistError):
			send_message("JCONV-99999", "hi")

	def test_persists_user_message_and_enqueues_worker(self):
		with patch("jarvis.chat.api._ensure_session_key", return_value="agent:fake"):
			with patch("frappe.enqueue") as enqueue:
				result = send_message(self.conv, "list 3 customers")
		self.assertTrue(result["ok"])
		# A user message row exists
		rows = frappe.get_all(
			MSG,
			filters={"conversation": self.conv, "role": "user"},
			fields=["name", "seq", "content"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["seq"], 1)
		self.assertEqual(rows[0]["content"], "list 3 customers")
		# The worker was enqueued with the right kwargs
		enqueue.assert_called_once()
		_, kwargs = enqueue.call_args
		self.assertEqual(kwargs["method"], "jarvis.chat.worker.run_agent_turn")
		self.assertEqual(kwargs["conversation_id"], self.conv)
		self.assertEqual(kwargs["message_id"], result["message_id"])

	def test_seq_increments_across_calls(self):
		with patch("jarvis.chat.api._ensure_session_key", return_value="agent:fake"):
			with patch("frappe.enqueue"):
				send_message(self.conv, "a")
				send_message(self.conv, "b")
		seqs = frappe.get_all(
			MSG,
			filters={"conversation": self.conv, "role": "user"},
			fields=["seq"],
			order_by="seq asc",
		)
		self.assertEqual([r["seq"] for r in seqs], [1, 2])

	def test_first_message_sets_conversation_title(self):
		with patch("jarvis.chat.api._ensure_session_key", return_value="agent:fake"):
			with patch("frappe.enqueue"):
				send_message(self.conv, "How many invoices last quarter?")
		doc = frappe.get_doc(CONV, self.conv)
		self.assertEqual(doc.title, "How many invoices last quarter?")

	def test_bumps_last_active_at(self):
		before = frappe.utils.get_datetime(frappe.get_value(
			CONV, self.conv, "last_active_at"
		))
		with patch("jarvis.chat.api._ensure_session_key", return_value="agent:fake"):
			with patch("frappe.enqueue"):
				send_message(self.conv, "hi")
		after = frappe.utils.get_datetime(frappe.get_value(
			CONV, self.conv, "last_active_at"
		))
		self.assertGreaterEqual(after, before)


class TestRetryMessage(_ChatTestCase):
	"""retry_message re-runs the worker for the user turn that preceded an
	errored assistant message.
	"""

	def _make_turn(self, conv: str, user_text: str = "list 3 customers", with_error: bool = False) -> tuple[str, str]:
		"""Seed a conversation with a user message + assistant message at the
		next two seq values. Returns (user_message_name, assistant_message_name).
		"""
		base_seq = frappe.db.sql(
			"SELECT COALESCE(MAX(seq), 0) FROM `tabJarvis Chat Message` WHERE conversation = %s",
			(conv,),
		)[0][0]
		user_doc = frappe.get_doc({
			"doctype": MSG, "conversation": conv, "seq": base_seq + 1,
			"role": "user", "content": user_text,
		})
		user_doc.insert()
		asst_payload = {
			"doctype": MSG, "conversation": conv, "seq": base_seq + 2,
			"role": "assistant", "content": "",
		}
		if with_error:
			asst_payload["error"] = "rate limit"
		asst_doc = frappe.get_doc(asst_payload)
		asst_doc.insert()
		frappe.db.commit()
		return user_doc.name, asst_doc.name

	def setUp(self):
		super().setUp()
		self.conv = create_conversation()

	def test_enqueues_worker_against_preceding_user_message(self):
		user_id, asst_id = self._make_turn(self.conv, with_error=True)
		with patch("frappe.enqueue") as enqueue:
			result = retry_message(asst_id)
		self.assertTrue(result["ok"])
		self.assertIn("run_id", result)
		enqueue.assert_called_once()
		_, kwargs = enqueue.call_args
		self.assertEqual(kwargs["method"], "jarvis.chat.worker.run_agent_turn")
		self.assertEqual(kwargs["conversation_id"], self.conv)
		self.assertEqual(kwargs["message_id"], user_id)

	def test_rejects_non_assistant_message(self):
		user_id, _asst_id = self._make_turn(self.conv, with_error=True)
		result = retry_message(user_id)
		self.assertFalse(result["ok"])
		self.assertIn("assistant", result["reason"].lower())

	def test_rejects_message_without_error(self):
		_user_id, asst_id = self._make_turn(self.conv, with_error=False)
		result = retry_message(asst_id)
		self.assertFalse(result["ok"])
		self.assertIn("error", result["reason"].lower())

	def test_rejects_if_no_preceding_user_message(self):
		"""An orphan errored assistant (somehow inserted without a user) — refuse."""
		asst_doc = frappe.get_doc({
			"doctype": MSG, "conversation": self.conv, "seq": 1,
			"role": "assistant", "content": "", "error": "boom",
		})
		asst_doc.insert()
		frappe.db.commit()
		result = retry_message(asst_doc.name)
		self.assertFalse(result["ok"])
		self.assertIn("preceding", result["reason"].lower())

	def test_picks_immediately_preceding_user_message(self):
		"""When a conversation has multiple user turns, retry should target the
		one right before the errored assistant, not an older one.
		"""
		_u1, _a1 = self._make_turn(self.conv, user_text="first turn", with_error=False)
		u2, _a2 = self._make_turn(self.conv, user_text="second turn", with_error=False)
		# Insert a fresh errored assistant after u2
		seq_max = frappe.db.sql(
			"SELECT MAX(seq) FROM `tabJarvis Chat Message` WHERE conversation = %s",
			(self.conv,),
		)[0][0]
		errored = frappe.get_doc({
			"doctype": MSG, "conversation": self.conv, "seq": seq_max + 1,
			"role": "assistant", "content": "", "error": "rate limit",
		})
		errored.insert()
		frappe.db.commit()

		with patch("frappe.enqueue") as enqueue:
			retry_message(errored.name)
		_, kwargs = enqueue.call_args
		self.assertEqual(kwargs["message_id"], u2)

	def test_bumps_conversation_last_active_at(self):
		_u, asst_id = self._make_turn(self.conv, with_error=True)
		before = frappe.utils.get_datetime(frappe.get_value(
			CONV, self.conv, "last_active_at"
		))
		with patch("frappe.enqueue"):
			retry_message(asst_id)
		after = frappe.utils.get_datetime(frappe.get_value(
			CONV, self.conv, "last_active_at"
		))
		self.assertGreaterEqual(after, before)
