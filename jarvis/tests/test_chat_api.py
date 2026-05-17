"""Tests for jarvis.chat.api — whitelisted endpoints."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.api import (
	archive_conversation,
	create_conversation,
	get_conversation,
	list_conversations,
)

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"


def _cleanup_user_conversations(user: str):
	"""Delete all conversations owned by user (and their messages)."""
	names = frappe.get_all(CONV, filters={"owner": user}, pluck="name")
	for name in names:
		for child in frappe.get_all(MSG, filters={"conversation": name}, pluck="name"):
			frappe.delete_doc(MSG, child, ignore_permissions=True, force=True)
		frappe.delete_doc(CONV, name, ignore_permissions=True, force=True)
	frappe.db.commit()


class TestCreateConversation(FrappeTestCase):
	def setUp(self):
		_cleanup_user_conversations("Administrator")

	def tearDown(self):
		_cleanup_user_conversations("Administrator")

	def test_creates_a_row_owned_by_current_user(self):
		name = create_conversation()
		doc = frappe.get_doc(CONV, name)
		self.assertEqual(doc.owner, "Administrator")
		self.assertEqual(doc.status, "active")
		self.assertIsNotNone(doc.last_active_at)

	def test_title_defaults_to_new_chat(self):
		name = create_conversation()
		doc = frappe.get_doc(CONV, name)
		self.assertEqual(doc.title, "New chat")


class TestListConversations(FrappeTestCase):
	def setUp(self):
		_cleanup_user_conversations("Administrator")

	def tearDown(self):
		_cleanup_user_conversations("Administrator")

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


class TestGetConversation(FrappeTestCase):
	def setUp(self):
		_cleanup_user_conversations("Administrator")

	def tearDown(self):
		_cleanup_user_conversations("Administrator")

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


class TestArchiveConversation(FrappeTestCase):
	def setUp(self):
		_cleanup_user_conversations("Administrator")

	def tearDown(self):
		_cleanup_user_conversations("Administrator")

	def test_sets_status_to_archived(self):
		name = create_conversation()
		archive_conversation(name)
		doc = frappe.get_doc(CONV, name)
		self.assertEqual(doc.status, "archived")
