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


class TestPerModelAttribution(_Base):
	def _row(self, **kw):
		base = {
			"totalTokensFresh": True,
			"inputTokens": 0,
			"outputTokens": 0,
			"totalTokens": 0,
			"model": "gpt-4o",
		}
		base.update(kw)
		return base

	def _child(self, model):
		return frappe.db.get_value(
			MODEL_USAGE,
			{
				"parent": USER_A,
				"parenttype": USETT,
				"parentfield": "user_model_usage",
				"model": model,
				"month_key": usage.current_month_key(),
			},
			["month_input_tokens", "month_output_tokens", "monthly_token_limit"],
			as_dict=True,
		)

	def test_upserts_and_accumulates_per_model(self):
		_make_session("agent:pm1", USER_A)
		usage.record_turn_usage("agent:pm1", self._row(model="gpt-4o", inputTokens=10, outputTokens=5))
		usage.record_turn_usage("agent:pm1", self._row(model="gpt-4o", inputTokens=8, outputTokens=12))
		usage.record_turn_usage("agent:pm1", self._row(model="claude-sonnet", inputTokens=3, outputTokens=4))
		g = self._child("gpt-4o")
		self.assertEqual(g.month_input_tokens, 18)
		self.assertEqual(g.month_output_tokens, 17)
		c = self._child("claude-sonnet")
		self.assertEqual(c.month_input_tokens, 3)
		self.assertEqual(c.month_output_tokens, 4)

	def test_missing_model_field_tolerated_no_child_row(self):
		_make_session("agent:pm2", USER_A)
		# No "model" key: aggregate still records; no child row is created; no raise.
		usage.record_turn_usage("agent:pm2", {"totalTokensFresh": True, "inputTokens": 5, "outputTokens": 5})
		self.assertEqual(frappe.utils.cint(frappe.db.get_value(USETT, {"user": USER_A}, "month_tokens")), 10)
		self.assertEqual(frappe.get_all(MODEL_USAGE, filters={"parent": USER_A}), [])

	def test_month_rollover_prunes_stale_usage_and_carries_cap(self):
		_make_session("agent:pm3", USER_A)
		usage.record_turn_usage("agent:pm3", self._row(model="gpt-4o", inputTokens=10, outputTokens=5))
		# Give gpt-4o a cap and mark its row + the parent as a prior month.
		usage.set_model_limit(USER_A, "gpt-4o", 1000)
		frappe.db.set_value(
			MODEL_USAGE,
			{"parent": USER_A, "model": "gpt-4o", "month_key": usage.current_month_key()},
			"month_key",
			"2020-01",
			update_modified=False,
		)
		# A zero-cap stale row that must be pruned on the next record.
		usage.record_turn_usage("agent:pm3", self._row(model="oldmodel", inputTokens=1, outputTokens=1))
		frappe.db.set_value(
			MODEL_USAGE,
			{"parent": USER_A, "model": "oldmodel", "month_key": usage.current_month_key()},
			"month_key",
			"2020-01",
			update_modified=False,
		)
		frappe.db.commit()
		# New turn on gpt-4o this month: fresh current-month row, cap carried, delta reset.
		usage.record_turn_usage("agent:pm3", self._row(model="gpt-4o", inputTokens=7, outputTokens=3))
		g = self._child("gpt-4o")
		self.assertEqual(g.month_input_tokens, 7)  # reset to new delta
		self.assertEqual(g.month_output_tokens, 3)
		self.assertEqual(g.monthly_token_limit, 1000)  # cap survived rollover
		# Stale zero-cap row pruned; no stale gpt-4o row remains.
		self.assertEqual(frappe.get_all(MODEL_USAGE, filters={"parent": USER_A, "month_key": "2020-01"}), [])

	def test_set_model_limit_creates_row_without_usage(self):
		usage.get_or_create_user_settings(USER_A)
		usage.set_model_limit(USER_A, "gpt-4o", 500)
		g = self._child("gpt-4o")
		self.assertIsNotNone(g)
		self.assertEqual(g.monthly_token_limit, 500)
		self.assertEqual(g.month_input_tokens, 0)

	def test_never_raises_on_bad_model_write(self):
		# A malformed model value must not break the turn (G1). Empty string is
		# treated as "no model" and simply records the aggregate only.
		_make_session("agent:pm4", USER_A)
		usage.record_turn_usage("agent:pm4", self._row(model="", inputTokens=4, outputTokens=4))
		self.assertEqual(frappe.get_all(MODEL_USAGE, filters={"parent": USER_A}), [])
