"""The test suite must be incapable of touching a live tenant.

Jarvis Settings.on_update runs the admin sync INLINE under frappe.flags.in_test, and
that sync's transport is jarvis.admin_client. On CI nothing answers, so the call fails
harmlessly -- CI has only ever been safe BY ACCIDENT. On a developer's bench,
jarvis.admin and the fleet-agent ARE running, so the same call SUCCEEDS and pushes the
test's FIXTURE pool into a real tenant: rewriting its bifrost config, tearing down
cliproxy via --remove-orphans, and deleting the OAuth token blob. There is no undo --
Frappe keeps no Version history for a Single.

On 2026-07-14 `bench --site site.jarvis run-tests --app jarvis` did exactly that: it
destroyed a live tenant's LLM pool and an OAuth subscription credential that could not
be recovered, and left a `models=[] with proxy_active=1` state that was then
misdiagnosed for hours as an on_update ordering race.

These tests make the guard the thing that fails, loudly, instead.
"""
import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis import admin_client
from jarvis.exceptions import AdminUnreachableError, OpenclawUnreachableError


class TestAdminClientOutboundGuard(FrappeTestCase):
	def test_real_admin_call_is_blocked_under_test(self):
		"""The whole point: a test must not be able to reach admin/the fleet."""
		with patch("jarvis.admin_client.requests.post") as post:
			with self.assertRaises(AdminUnreachableError) as ctx:
				admin_client._do_post(
					"http://jarvis.admin:8002/api/method/x", {}, {}, 10,
					"http://jarvis.admin:8002",
				)
			post.assert_not_called(), "the guard must fire BEFORE the socket is opened"
		self.assertIn("BLOCKED", str(ctx.exception))

	def test_the_guard_fires_before_any_socket_is_opened(self):
		"""Not "the call fails" -- the call must never LEAVE. A guard that lets the
		request out and then complains has already rewritten the tenant."""
		with patch("jarvis.admin_client.requests.post") as post:
			with self.assertRaises(AdminUnreachableError):
				admin_client._do_post("http://x/y", {"models": ["fixture"]}, {}, 5, "http://x")
		post.assert_not_called()

	def test_it_raises_the_SAME_error_a_dead_admin_raises(self):
		"""AdminUnreachableError, deliberately -- so a local run behaves exactly as CI
		already does (where nothing answers) and every existing caller's error handling
		applies unchanged. A novel exception type would change test outcomes."""
		with self.assertRaises(AdminUnreachableError):
			admin_client._do_post("http://x/y", {}, {}, 5, "http://x")

	def test_an_explicit_opt_in_still_allows_a_real_call(self):
		"""The escape hatch exists, and nothing in the ordinary suite sets it."""
		frappe.flags.allow_real_admin_calls = True
		try:
			with patch("jarvis.admin_client.requests.post") as post:
				post.return_value.status_code = 200
				post.return_value.json.return_value = {"message": {"ok": True}}
				admin_client._do_post("http://x/y", {}, {}, 5, "http://x")
			post.assert_called_once()
		finally:
			frappe.flags.allow_real_admin_calls = False

	def test_the_oauth_token_egress_is_guarded_too(self):
		"""admin_client has TWO ways out. Guarding only _do_post would leave the token
		grab free to hit a live admin."""
		with patch("jarvis.admin_client.requests.post") as post:
			with self.assertRaises(AdminUnreachableError):
				admin_client._oauth_token_request(
					"http://jarvis.admin:8002", {"grant_type": "password"})
			post.assert_not_called()


class TestOpenclawConnectGuard(FrappeTestCase):
	def test_real_gateway_connection_is_blocked_under_test(self):
		"""A test that forgets to mock the gateway would otherwise talk to the live
		container: mutating session state via sessions.patch, appending to its durable
		transcript, and burning real tokens from the customer's LLM quota -- while
		passing green."""
		from jarvis.chat.openclaw_client import OpenclawSession

		with self.assertRaises(OpenclawUnreachableError) as ctx:
			OpenclawSession.connect("ws://localhost:19300")
		self.assertIn("BLOCKED", str(ctx.exception))


if __name__ == "__main__":
	unittest.main()


class TestTheGuardIsOnEVERYEgress(FrappeTestCase):
	"""A guard with holes gives false confidence. The app has SIX ways onto the network;
	all six route through jarvis._test_guard, so there is one policy and one place to
	reason about it."""

	EGRESS_MODULES = [
		"jarvis.admin_client",       # rewrites the tenant pool, deletes OAuth blobs
		"jarvis.chat.openclaw_client",  # mutates live session state, burns LLM quota
		"jarvis.oauth.api",          # exchanges/refreshes REAL provider tokens
		"jarvis.chat.voice",         # burns real STT quota
		"jarvis.selfhost",           # probes a real customer LLM endpoint
		"jarvis.chat.link_fetch",    # fetches arbitrary URLs off the open internet
	]

	def test_every_module_that_can_reach_the_network_consults_the_guard(self):
		import importlib
		import inspect

		for name in self.EGRESS_MODULES:
			mod = importlib.import_module(name)
			src = inspect.getsource(mod)
			self.assertIn(
				"_test_guard", src,
				f"{name} can reach the network but does not consult jarvis._test_guard. "
				"A new egress must be guarded, or the suite can touch a live tenant again.",
			)

	def test_the_guard_is_inert_outside_a_test_run(self):
		"""Production must be untouched. frappe.flags.in_test is set by the test runner
		and by nothing else -- if this ever fired in prod it would break every real
		customer sync."""
		from jarvis import _test_guard

		saved = frappe.flags.get("in_test")
		try:
			frappe.flags.in_test = False
			self.assertIsNone(_test_guard.blocked_reason("http://admin/x"))
		finally:
			frappe.flags.in_test = saved
