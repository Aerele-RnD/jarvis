"""Tests for ``jarvis._session.impersonate`` - the session-safe replacement for
a bare ``frappe.set_user`` inside cookie-session HTTP request paths.

The bug it guards against: ``frappe.set_user`` sets ``session.sid`` to the
username string and REPLACES ``session.data`` with an empty dict. Inside a
request, end-of-request ``Session.update`` then re-persists the gutted data
under the browser's REAL sid (a ``__slots__`` attribute set_user doesn't
touch), poisoning that sid's Redis cache entry -> the user is logged out on the
next request. impersonate snapshots + restores ``sid`` and ``data`` so the real
cookie session stays intact.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis._session import impersonate


class TestImpersonate(FrappeTestCase):
	# "Guest" always exists and switching to it exercises the exact set_user
	# behaviour we guard (sid -> username string, data -> empty dict) without a
	# test-only User insert (which pulls in unrelated notification-settings deps).
	_OTHER = "Guest"

	def test_switch_preserves_sid_and_data(self):
		other = self._OTHER
		orig_user = frappe.session.user
		orig_sid = frappe.session.sid
		orig_data = frappe.session.data
		frappe.session.data.csrf_token = "SENTINEL-IMP-1"

		with impersonate(other):
			# Inside the block we ARE the other user...
			self.assertEqual(frappe.session.user, other)
			# ...and set_user has (correctly) swapped sid + data underneath us.
			self.assertNotEqual(frappe.session.sid, orig_sid)

		# After the block the original cookie session is fully restored:
		# user name, sid, and the SAME data object (incl. the sentinel).
		self.assertEqual(frappe.session.user, orig_user)
		self.assertEqual(frappe.session.sid, orig_sid)
		self.assertIs(frappe.session.data, orig_data)
		self.assertEqual(frappe.session.data.csrf_token, "SENTINEL-IMP-1")

	def test_same_user_is_a_true_noop(self):
		# impersonate(current user) must NOT call frappe.set_user at all - even
		# set_user(same_user) guts sid + data.
		current = frappe.session.user
		with patch("jarvis._session.frappe.set_user") as m:
			with impersonate(current):
				self.assertEqual(frappe.session.user, current)
		m.assert_not_called()

	def test_falsy_user_is_a_true_noop(self):
		current = frappe.session.user
		for val in (None, ""):
			with patch("jarvis._session.frappe.set_user") as m:
				with impersonate(val):
					self.assertEqual(frappe.session.user, current)
			m.assert_not_called()

	def test_exception_in_block_still_restores(self):
		other = self._OTHER
		orig_user = frappe.session.user
		orig_sid = frappe.session.sid
		orig_data = frappe.session.data
		frappe.session.data.csrf_token = "SENTINEL-IMP-2"

		with self.assertRaises(ValueError):
			with impersonate(other):
				raise ValueError("boom")

		self.assertEqual(frappe.session.user, orig_user)
		self.assertEqual(frappe.session.sid, orig_sid)
		self.assertIs(frappe.session.data, orig_data)
		self.assertEqual(frappe.session.data.csrf_token, "SENTINEL-IMP-2")

	def test_nested_impersonation_restores_each_layer(self):
		other = self._OTHER
		orig_user = frappe.session.user
		orig_sid = frappe.session.sid
		orig_data = frappe.session.data

		with impersonate(other):
			mid_sid = frappe.session.sid
			mid_data = frappe.session.data
			self.assertEqual(frappe.session.user, other)
			# Nesting back to the original user from inside the other-user block
			# is a real switch (other -> orig), then restores to `other`.
			with impersonate(orig_user):
				self.assertEqual(frappe.session.user, orig_user)
			self.assertEqual(frappe.session.user, other)
			self.assertEqual(frappe.session.sid, mid_sid)
			self.assertIs(frappe.session.data, mid_data)

		self.assertEqual(frappe.session.user, orig_user)
		self.assertEqual(frappe.session.sid, orig_sid)
		self.assertIs(frappe.session.data, orig_data)
