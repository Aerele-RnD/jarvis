"""Tests for the periodic business-pulse survey's backend: the lazy
period-key gate on ``Jarvis User Settings`` and the two whitelisted endpoints.

Fixture shape mirrors ``test_session_feedback.py`` (a dedicated disposable
user, real conversations via ``create_conversation``) rather than a
rollback-only one: the settings row is created by
``usage.get_or_create_user_settings`` and other tests commit, so every case
resets the two pulse fields itself instead of trusting a clean row.

The admin forward is always mocked - these never hit a real admin.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.chat.api import create_conversation
from jarvis.chat.feedback import (
	PULSE_MAX_OFFERS,
	PULSE_SURVEY_CADENCE,
	pulse_context,
	submit_pulse_feedback,
)
from jarvis.chat.usage import current_period_key, get_or_create_user_settings

CONV = "Jarvis Conversation"
MSG = "Jarvis Chat Message"
TURN = "Jarvis Chat Turn"
SETTINGS = "Jarvis User Settings"
TEST_USER = "jarvis-pulse-feedback-test@example.com"

_PUSH = "jarvis.admin_client.push_pulse_feedback"
_FEATURES = "jarvis.chat.feature_usage.get_used_features"
#: A key that can never be the current one, so the row reads as "last offered
#: in some earlier period".
_STALE_KEY = "M:1999-01"


def _ensure_test_user(user: str = TEST_USER) -> None:
	if frappe.db.exists("User", user):
		return
	doc = frappe.get_doc(
		{
			"doctype": "User",
			"email": user,
			"first_name": "Pulse",
			"last_name": "Feedback",
			"enabled": 1,
			"send_welcome_email": 0,
			"user_type": "System User",
		}
	).insert(ignore_permissions=True)
	doc.add_roles("System Manager")
	frappe.db.commit()


def _delete_conv(name: str) -> None:
	for turn in frappe.get_all(TURN, filters={"conversation": name}, pluck="name"):
		frappe.delete_doc(TURN, turn, ignore_permissions=True, force=True)
	for child in frappe.get_all(MSG, filters={"conversation": name}, pluck="name"):
		frappe.delete_doc(MSG, child, ignore_permissions=True, force=True)
	if frappe.db.exists(CONV, name):
		frappe.delete_doc(CONV, name, ignore_permissions=True, force=True)
	frappe.db.commit()


def _cleanup_user_conversations(user: str = TEST_USER) -> None:
	for name in frappe.get_all(CONV, filters={"owner": user}, pluck="name"):
		_delete_conv(name)


class _PulseTestCase(FrappeTestCase):
	def setUp(self):
		_ensure_test_user()
		self._orig_user = frappe.session.user
		frappe.set_user(TEST_USER)
		_cleanup_user_conversations()
		self.settings = get_or_create_user_settings(TEST_USER).name
		self._set_pulse(None, 0)
		# One conversation with a settled turn inside the window, so the "had at
		# least one turn in the period" gate passes unless a case says otherwise.
		self.conv = create_conversation()
		self._set_turns(5)

	def tearDown(self):
		self._set_pulse(None, 0)
		_cleanup_user_conversations()
		frappe.set_user(self._orig_user)

	def _set_pulse(self, key, count):
		frappe.db.set_value(
			SETTINGS,
			self.settings,
			{"pulse_last_period_key": key, "pulse_offer_count": count},
			update_modified=False,
		)

	def _pulse(self):
		return frappe.db.get_value(
			SETTINGS, self.settings, ["pulse_last_period_key", "pulse_offer_count"], as_dict=True
		)

	def _set_turns(self, count, *, days_ago=0, conversation=None):
		frappe.db.set_value(
			CONV,
			conversation or self.conv,
			{
				"turn_count": count,
				"last_active_at": frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-days_ago),
			},
			update_modified=False,
		)


class TestPulseContext(_PulseTestCase):
	def test_due_when_never_offered(self):
		with patch(_FEATURES, return_value={}):
			result = pulse_context()
		self.assertTrue(result["due"])
		self.assertEqual(result["period_key"], current_period_key(PULSE_SURVEY_CADENCE))
		self.assertTrue(result["period_label"].startswith("This month,"))

	def test_an_offer_stamps_the_current_period_and_counts_one(self):
		with patch(_FEATURES, return_value={}):
			pulse_context()
		row = self._pulse()
		self.assertEqual(row.pulse_last_period_key, current_period_key(PULSE_SURVEY_CADENCE))
		self.assertEqual(row.pulse_offer_count, 1)

	def test_maybe_later_re_offers_up_to_the_cap_then_goes_quiet(self):
		"""'Maybe later' is not recorded anywhere - the survey simply comes back
		on the next chat opens, three times in all, and then stops nagging."""
		with patch(_FEATURES, return_value={}):
			for expected in range(1, PULSE_MAX_OFFERS + 1):
				self.assertTrue(pulse_context()["due"], f"offer {expected} should be due")
				self.assertEqual(self._pulse().pulse_offer_count, expected)
			self.assertFalse(pulse_context()["due"], "capped, so quiet for the rest of the period")
		self.assertEqual(self._pulse().pulse_offer_count, PULSE_MAX_OFFERS, "the cap is not exceeded")

	def test_a_new_period_resets_the_offer_count(self):
		"""The cap must RESET on rollover, not merely stop decrementing: a user
		exhausted last month is due again this month, at count 1."""
		self._set_pulse(_STALE_KEY, PULSE_MAX_OFFERS)
		with patch(_FEATURES, return_value={}):
			self.assertTrue(pulse_context()["due"])
		row = self._pulse()
		self.assertEqual(row.pulse_last_period_key, current_period_key(PULSE_SURVEY_CADENCE))
		self.assertEqual(row.pulse_offer_count, 1)

	def test_capped_never_computes_the_feature_list(self):
		"""The cheap period-key comparison gates the comparatively expensive
		feature-usage sweep (spec: performance review)."""
		self._set_pulse(current_period_key(PULSE_SURVEY_CADENCE), PULSE_MAX_OFFERS)
		with patch(_FEATURES) as features:
			self.assertFalse(pulse_context()["due"])
		features.assert_not_called()

	def test_no_turns_at_all_is_not_due(self):
		self._set_turns(0)
		with patch(_FEATURES) as features:
			self.assertFalse(pulse_context()["due"])
		features.assert_not_called()
		self.assertIsNone(self._pulse().pulse_last_period_key, "a non-offer burns nothing")

	def test_turns_only_outside_the_window_are_not_due(self):
		self._set_turns(50, days_ago=60)
		with patch(_FEATURES) as features:
			self.assertFalse(pulse_context()["due"])
		features.assert_not_called()

	def test_turns_are_summed_across_the_users_conversations(self):
		"""A user with several shallow conversations still qualifies: the gate is
		the SUM of turn_count in the window, not any single conversation."""
		self._set_turns(0)
		second = create_conversation()
		self._set_turns(1, conversation=second)
		with patch(_FEATURES, return_value={}):
			self.assertTrue(pulse_context()["due"])

	def test_features_offered_may_be_empty_but_the_survey_is_still_due(self):
		# Stars and the open question are still worth asking; only the chip
		# question hides client-side when this list is empty.
		with patch(_FEATURES, return_value={}):
			result = pulse_context()
		self.assertTrue(result["due"])
		self.assertEqual(result["features_offered"], [])

	def test_features_offered_are_the_used_keys_in_canonical_order(self):
		# feature_usage.FEATURES order, not alphabetical: the dialog renders the
		# chips in the order it receives them, and both endpoints agree on it.
		with patch(_FEATURES, return_value={"dashboard_builder": "2026-09-01", "file_box": "2026-09-02"}):
			result = pulse_context()
		self.assertEqual(result["features_offered"], ["file_box", "dashboard_builder"])


class TestSubmitPulseFeedback(_PulseTestCase):
	def _item(self, push):
		push.assert_called_once()
		return push.call_args.args[0]

	def test_forwards_a_derived_payload(self):
		with patch(_PUSH) as push:
			res = submit_pulse_feedback(
				stars=4,
				features_offered=["file_box", "wiki"],
				features_selected=["file_box"],
				use_case_text="  saves us hours a week  ",
				note="  more charts please  ",
			)
		self.assertEqual(res, {"ok": True})
		item = self._item(push)
		self.assertEqual(item["kind"], "Pulse")
		self.assertEqual(item["stars"], 4)
		self.assertEqual(item["period_key"], current_period_key(PULSE_SURVEY_CADENCE))
		self.assertEqual(item["features_offered"], ["file_box", "wiki"])
		self.assertEqual(item["features_selected"], ["file_box"])
		self.assertEqual(item["use_case_text"], "saves us hours a week")
		self.assertEqual(item["note"], "more charts please")
		self.assertEqual(item["user_ref"], TEST_USER)

	def test_accepts_json_encoded_lists_from_the_client(self):
		# frappe.client passes list args as JSON strings over HTTP.
		with patch(_PUSH) as push:
			submit_pulse_feedback(stars=5, features_offered='["wiki"]', features_selected='["wiki"]')
		item = self._item(push)
		self.assertEqual(item["features_offered"], ["wiki"])
		self.assertEqual(item["features_selected"], ["wiki"])

	def test_unknown_feature_keys_are_dropped(self):
		with patch(_PUSH) as push:
			submit_pulse_feedback(
				stars=3, features_offered=["wiki", "not_a_feature", 7], features_selected=["nope"]
			)
		item = self._item(push)
		self.assertEqual(item["features_offered"], ["wiki"])
		self.assertEqual(item["features_selected"], [])

	def test_rejects_stars_outside_one_to_five(self):
		# Non-numeric too: over HTTP every argument arrives as a string, so a
		# broken client must get the same validation error, never a 500.
		for bad in (0, 6, -1, "abc", None):
			with self.subTest(stars=bad):
				with patch(_PUSH) as push:
					with self.assertRaises(frappe.ValidationError):
						submit_pulse_feedback(stars=bad, features_offered=[], features_selected=[])
				push.assert_not_called()
				self.assertIsNone(
					self._pulse().pulse_last_period_key, "a rejected submit must not silence the survey"
				)

	def test_accepts_the_whole_one_to_five_range(self):
		for stars in range(1, 6):
			with self.subTest(stars=stars):
				with patch(_PUSH) as push:
					submit_pulse_feedback(stars=stars, features_offered=[], features_selected=[])
				self.assertEqual(self._item(push)["stars"], stars)

	def test_answering_silences_the_survey_for_the_rest_of_the_period(self):
		with patch(_PUSH):
			submit_pulse_feedback(stars=5, features_offered=[], features_selected=[])
		row = self._pulse()
		self.assertEqual(row.pulse_last_period_key, current_period_key(PULSE_SURVEY_CADENCE))
		self.assertEqual(row.pulse_offer_count, PULSE_MAX_OFFERS)
		with patch(_FEATURES) as features:
			self.assertFalse(pulse_context()["due"])
		features.assert_not_called()

	def test_answering_does_not_silence_the_next_period(self):
		with patch(_PUSH):
			submit_pulse_feedback(stars=5, features_offered=[], features_selected=[])
		# Simulate the rollover the same way a real month boundary presents it.
		self._set_pulse(_STALE_KEY, PULSE_MAX_OFFERS)
		with patch(_FEATURES, return_value={}):
			self.assertTrue(pulse_context()["due"])

	def test_a_failed_forward_never_surfaces_and_still_silences(self):
		with patch(_PUSH, side_effect=RuntimeError("admin down")):
			res = submit_pulse_feedback(stars=2, features_offered=[], features_selected=[])
		self.assertEqual(res, {"ok": True})
		self.assertEqual(self._pulse().pulse_offer_count, PULSE_MAX_OFFERS)

	def test_free_text_is_bounded(self):
		with patch(_PUSH) as push:
			submit_pulse_feedback(
				stars=1,
				features_offered=[],
				features_selected=[],
				use_case_text="x" * 5000,
				note="y" * 5000,
			)
		item = self._item(push)
		self.assertEqual(len(item["use_case_text"]), 1000)
		self.assertEqual(len(item["note"]), 1000)
