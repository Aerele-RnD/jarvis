"""Tests for per-model usage accounting + caps (fleet usage spec §7, §9).

Hermetic like test_user_settings.py: disposable enabled users created in setUp,
and because record_turn_usage / set_model_limit COMMIT, every Jarvis User
Settings + Jarvis Chat Session + Jarvis User Model Usage row owned by a fixture
user is deleted in tearDown (a transaction rollback cannot undo a commit).
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import usage

USETT = "Jarvis User Settings"
SESSION = "Jarvis Chat Session"
MODEL_USAGE = "Jarvis User Model Usage"

USER_A = "jarvis-permodel-a@example.test"
_ALL_USERS = (USER_A,)


def _ensure_user(email: str) -> None:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Jarvis",
				"last_name": "PerModelTest",
				"enabled": 1,
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		).insert(ignore_permissions=True)


def _make_session(session_key: str, user: str) -> None:
	frappe.get_doc(
		{
			"doctype": SESSION,
			"session_key": session_key,
			"user": user,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()


def _cleanup() -> None:
	for email in _ALL_USERS:
		for name in frappe.get_all(MODEL_USAGE, filters={"parent": email}, pluck="name"):
			frappe.delete_doc(MODEL_USAGE, name, ignore_permissions=True, force=True)
		for name in frappe.get_all(USETT, filters={"user": email}, pluck="name"):
			frappe.delete_doc(USETT, name, ignore_permissions=True, force=True)
		for name in frappe.get_all(SESSION, filters={"user": email}, pluck="name"):
			frappe.delete_doc(SESSION, name, ignore_permissions=True, force=True)


class _Base(FrappeTestCase):
	def setUp(self):
		self._orig_user = frappe.session.user
		frappe.set_user("Administrator")
		_ensure_user(USER_A)
		_cleanup()
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		_cleanup()
		frappe.db.commit()
		frappe.set_user(self._orig_user)


class TestChildDoctypeSchema(_Base):
	def test_child_doctype_exists_with_fields(self):
		meta = frappe.get_meta(MODEL_USAGE)
		self.assertTrue(meta.istable)
		fields = {f.fieldname: f for f in meta.fields}
		for fn in ("model", "month_key", "month_input_tokens", "month_output_tokens", "monthly_token_limit"):
			self.assertIn(fn, fields, f"missing child field {fn}")
		self.assertEqual(fields["month_input_tokens"].fieldtype, "Int")
		self.assertEqual(fields["monthly_token_limit"].fieldtype, "Int")

	def test_parent_has_permlevel1_table_field(self):
		meta = frappe.get_meta(USETT)
		f = {x.fieldname: x for x in meta.fields}.get("user_model_usage")
		self.assertIsNotNone(f, "parent missing user_model_usage table field")
		self.assertEqual(f.fieldtype, "Table")
		self.assertEqual(f.options, MODEL_USAGE)
		self.assertEqual(int(f.permlevel or 0), 1)
