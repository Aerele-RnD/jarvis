from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.api import call_tool


class TestCallToolStandardAuth(FrappeTestCase):
	"""Direct-Python invocation path: behaves like Phase 1, runs as the current session user."""

	def test_calls_tool_and_returns_result(self):
		result = call_tool(tool="get_schema", args={"doctype": "Customer"})
		self.assertEqual(result["ok"], True)
		self.assertEqual(result["data"]["doctype"], "Customer")

	def test_accepts_json_string_args(self):
		result = call_tool(tool="get_schema", args='{"doctype": "Customer"}')
		self.assertEqual(result["ok"], True)

	def test_unknown_tool_returns_error_envelope(self):
		result = call_tool(tool="not_a_tool", args={})
		self.assertEqual(result["ok"], False)
		self.assertEqual(result["error"]["code"], "ToolNotFoundError")

	def test_invalid_args_returns_error_envelope(self):
		result = call_tool(tool="get_doc", args={"doctype": "Customer"})
		self.assertEqual(result["ok"], False)
		self.assertEqual(result["error"]["code"], "InvalidArgumentError")


class _FakeRequest:
	"""Minimal request stand-in for the plugin-auth tests.

	Carries headers (the original use case) plus the raw body bytes so the
	HMAC validator can compute a body sha256. Defaults to empty body, which
	matches every non-signature test path.
	"""

	def __init__(self, headers: dict[str, str], body: bytes = b""):
		self.headers = headers
		self._body = body

	def get_data(self, cache: bool = True) -> bytes:
		return self._body


class TestCallToolPluginAuth(FrappeTestCase):
	"""Plugin-auth path: X-Jarvis-Token + X-Jarvis-Session → Frappe resolves
	the user from Jarvis Chat Session and dispatches as them.

	(The earlier shape required an X-Jarvis-User header which the plugin
	resolved via a separate HTTPS call. That round-trip was removed
	2026-05-18 - Frappe owns the session→user mapping, so it looks the
	user up itself. See architecture.md ‘Path A v2'.)
	"""

	SESSION_KEY = "agent:test:plugin-auth"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Jarvis Settings")
		# Use a dedicated token for plugin-auth tests so we don't depend on
		# real openclaw config. db_set bypasses on_update - the value persists
		# only for this test class.
		cls._original_token = settings.get_password("agent_token", raise_exception=False) or ""
		settings.db_set("agent_token", "plugin-auth-test-token")
		# Seed a Jarvis Chat Session row so the user-resolution lookup has
		# something to find. Use a sentinel key so we can clean up cleanly.
		_cleanup_session(cls.SESSION_KEY)
		frappe.get_doc({
			"doctype": "Jarvis Chat Session",
			"session_key": cls.SESSION_KEY,
			"user": "Administrator",
		}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("agent_token", cls._original_token)
		_cleanup_session(cls.SESSION_KEY)
		frappe.db.commit()
		super().tearDownClass()

	def _with_headers(self, headers: dict[str, str], *, body: bytes = b"",
	                  request_ip: str = "127.0.0.1"):
		"""Context manager: fakes ``frappe.request`` AND
		``frappe.local.request_ip``. Defaults to loopback so the
		C2 IP-allowlist check passes; tests targeting the IP path
		pass a different ``request_ip``.
		"""
		import contextlib
		req_patch = patch.object(frappe, "request", _FakeRequest(headers, body=body),
		                          create=True)
		# request_ip patch: frappe.local is a thread-local; just set the
		# attribute and restore on exit.
		@contextlib.contextmanager
		def _ip_ctx():
			prior = getattr(frappe.local, "request_ip", None)
			frappe.local.request_ip = request_ip
			try:
				yield
			finally:
				if prior is None:
					try: del frappe.local.request_ip
					except AttributeError: pass
				else:
					frappe.local.request_ip = prior

		@contextlib.contextmanager
		def _combined():
			with req_patch, _ip_ctx():
				yield
		return _combined()

	def test_valid_token_and_session_dispatches_as_session_user(self):
		"""Frappe resolves the user from the X-Jarvis-Session header alone."""
		seen_user: dict[str, str] = {}

		def spy_dispatch(name, args):
			seen_user["user"] = frappe.session.user
			return {"doctype": args["doctype"], "fields": []}

		with self._with_headers({
			"X-Jarvis-Token": "plugin-auth-test-token",
			"X-Jarvis-Session": self.SESSION_KEY,
		}):
			with patch("jarvis.api.dispatch", side_effect=spy_dispatch):
				with patch("jarvis.api._persist_and_publish_tool_call"):
					result = call_tool(tool="get_schema", args={"doctype": "Customer"})

		self.assertEqual(result["ok"], True)
		self.assertEqual(seen_user["user"], "Administrator")

	def test_invalid_token_returns_401(self):
		with self._with_headers({
			"X-Jarvis-Token": "wrong-token",
			"X-Jarvis-Session": self.SESSION_KEY,
		}):
			result = call_tool(tool="get_schema", args={"doctype": "Customer"})
		self.assertEqual(result["ok"], False)
		self.assertEqual(result["error"]["code"], "AuthenticationError")
		self.assertEqual(frappe.local.response.http_status_code, 401)

	def test_token_without_session_header_returns_400(self):
		with self._with_headers({"X-Jarvis-Token": "plugin-auth-test-token"}):
			result = call_tool(tool="get_schema", args={"doctype": "Customer"})
		self.assertEqual(result["ok"], False)
		self.assertEqual(result["error"]["code"], "InvalidArgumentError")
		self.assertIn("X-Jarvis-Session", result["error"]["message"])

	def test_token_with_unknown_session_returns_400(self):
		with self._with_headers({
			"X-Jarvis-Token": "plugin-auth-test-token",
			"X-Jarvis-Session": "agent:nonexistent:xyz",
		}):
			result = call_tool(tool="get_schema", args={"doctype": "Customer"})
		self.assertEqual(result["ok"], False)
		self.assertEqual(result["error"]["code"], "InvalidArgumentError")
		self.assertIn("unknown session", result["error"]["message"])

	def test_session_user_restored_after_dispatch(self):
		"""set_user is wrapped in try/finally - the calling user is preserved."""
		original = frappe.session.user
		with self._with_headers({
			"X-Jarvis-Token": "plugin-auth-test-token",
			"X-Jarvis-Session": self.SESSION_KEY,
		}):
			with patch("jarvis.api._persist_and_publish_tool_call"):
				call_tool(tool="get_schema", args={"doctype": "Customer"})
		self.assertEqual(frappe.session.user, original)


def _cleanup_session(session_key: str) -> None:
	names = frappe.get_all(
		"Jarvis Chat Session",
		filters={"session_key": session_key},
		pluck="name",
	)
	for name in names:
		frappe.delete_doc(
			"Jarvis Chat Session", name, ignore_permissions=True, force=True
		)
	frappe.db.commit()


# Sprint-1 / 2026-06-16 C2: layered plugin-auth defenses.
# See jarvis/_plugin_auth.py for the design.

class _PluginAuthTestBase(FrappeTestCase):
	"""Shared scaffolding: seed agent_token + a known Jarvis Chat Session
	so the existing call_tool flow has a user to dispatch under."""

	SESSION_KEY = "agent:test:c2"
	TOKEN = "c2-test-token"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		settings = frappe.get_single("Jarvis Settings")
		cls._orig_token = settings.get_password("agent_token", raise_exception=False) or ""
		settings.db_set("agent_token", cls.TOKEN)
		_cleanup_session(cls.SESSION_KEY)
		frappe.get_doc({
			"doctype": "Jarvis Chat Session",
			"session_key": cls.SESSION_KEY,
			"user": "Administrator",
		}).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		settings = frappe.get_single("Jarvis Settings")
		settings.db_set("agent_token", cls._orig_token)
		_cleanup_session(cls.SESSION_KEY)
		frappe.db.commit()
		super().tearDownClass()

	def _with_headers(self, headers, *, body=b"", request_ip="127.0.0.1"):
		import contextlib
		req_patch = patch.object(frappe, "request", _FakeRequest(headers, body=body),
		                          create=True)
		@contextlib.contextmanager
		def _ip_ctx():
			prior = getattr(frappe.local, "request_ip", None)
			frappe.local.request_ip = request_ip
			try:
				yield
			finally:
				if prior is None:
					try: del frappe.local.request_ip
					except AttributeError: pass
				else:
					frappe.local.request_ip = prior
		@contextlib.contextmanager
		def _combined():
			with req_patch, _ip_ctx():
				yield
		return _combined()

	def _call(self, *, request_ip="127.0.0.1", extra_headers=None, body=b""):
		headers = {
			"X-Jarvis-Token": self.TOKEN,
			"X-Jarvis-Session": self.SESSION_KEY,
		}
		if extra_headers:
			headers.update(extra_headers)
		with self._with_headers(headers, body=body, request_ip=request_ip):
			with patch("jarvis.api._persist_and_publish_tool_call"):
				return call_tool(tool="get_schema", args={"doctype": "Customer"})


class TestC2IpAllowlist(_PluginAuthTestBase):
	"""IP allowlist: default is loopback + RFC1918. A leaked agent_token
	used from the public internet must be rejected at the door."""

	def test_loopback_accepted_by_default(self):
		result = self._call(request_ip="127.0.0.1")
		self.assertTrue(result["ok"], msg=result)

	def test_rfc1918_docker_bridge_accepted_by_default(self):
		"""Docker bridge containers reach the bench from 172.17.0.x. This
		is the production traffic shape and must NOT be blocked."""
		result = self._call(request_ip="172.17.0.5")
		self.assertTrue(result["ok"], msg=result)

	def test_public_ipv4_rejected_with_403(self):
		result = self._call(request_ip="203.0.113.5")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "ForbiddenSourceIp")
		self.assertEqual(frappe.local.response.http_status_code, 403)

	def test_missing_request_ip_fails_closed(self):
		"""Defensive: if frappe.local.request_ip isn't set we must NOT
		default to allowing the request."""
		import contextlib
		headers = {
			"X-Jarvis-Token": self.TOKEN,
			"X-Jarvis-Session": self.SESSION_KEY,
		}
		req_patch = patch.object(frappe, "request",
		                          _FakeRequest(headers), create=True)
		@contextlib.contextmanager
		def _no_ip():
			prior = getattr(frappe.local, "request_ip", None)
			try:
				del frappe.local.request_ip
			except AttributeError:
				pass
			try:
				yield
			finally:
				if prior is not None:
					frappe.local.request_ip = prior
		with req_patch, _no_ip():
			result = call_tool(tool="get_schema", args={"doctype": "Customer"})
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "ForbiddenSourceIp")

	def test_custom_allowlist_with_wildcard_disables_check(self):
		"""Escape hatch for deploys that can't predict source IP (e.g.
		multi-host setups behind a proxy). "*" in the allowlist field
		bypasses the IP gate entirely. Operator opts in explicitly."""
		settings = frappe.get_single("Jarvis Settings")
		# Field may not exist yet on this site (migration pending) - the
		# code's try/except defaults to the hardcoded allowlist, so we
		# only run this test if the field is present.
		if "plugin_ip_allowlist" not in {f.fieldname for f in settings.meta.fields}:
			self.skipTest("plugin_ip_allowlist field not migrated yet")
		settings.db_set("plugin_ip_allowlist", "*")
		try:
			result = self._call(request_ip="203.0.113.5")
			self.assertTrue(result["ok"], msg=result)
		finally:
			settings.db_set("plugin_ip_allowlist", "")


class TestC2RateLimit(_PluginAuthTestBase):
	"""60 calls/min per session_key. Leaked-token spam protection."""

	def setUp(self):
		super().setUp()
		# Reset the rate-limit counter for this session before each test.
		# plugin_auth.py uses raw redis-py methods (set/incr/expire) which
		# are unnamespaced, so use raw delete here too.
		try:
			frappe.cache().delete(f"jarvis:plugin_rl:{self.SESSION_KEY}")
		except Exception:
			pass

	def test_under_limit_accepted(self):
		# A handful of calls back-to-back should all succeed.
		for _ in range(5):
			result = self._call()
			self.assertTrue(result["ok"], msg=result)

	def test_over_limit_returns_429(self):
		"""Exhaust the bucket; the 61st call is rejected with 429."""
		# Burn the budget directly via the rate-limit key to avoid 60
		# round-trips through call_tool's dispatch. Raw redis-py set so
		# the key matches plugin_auth.py's unnamespaced incr.
		cache = frappe.cache()
		key = f"jarvis:plugin_rl:{self.SESSION_KEY}"
		cache.set(key, 60, ex=60)
		result = self._call()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "RateLimitExceededError")
		self.assertEqual(frappe.local.response.http_status_code, 429)


class TestC2HmacSignature(_PluginAuthTestBase):
	"""Phase-2 HMAC: replay-proof signed requests. Plugin still sends
	bearer for backwards compat; the signature is additive."""

	def _signed_headers(self, *, body: bytes, ts: int = None,
	                    nonce: str = "deadbeefdeadbeefdeadbeef",
	                    bad_sig: bool = False):
		import hashlib
		import hmac as _hmac
		import time
		if ts is None:
			ts = int(time.time())
		body_hash = hashlib.sha256(body).hexdigest()
		canonical = "|".join([
			self.SESSION_KEY, body_hash, nonce, str(ts),
		]).encode("utf-8")
		sig = _hmac.new(self.TOKEN.encode("utf-8"), canonical,
		                hashlib.sha256).hexdigest()
		if bad_sig:
			# Flip a hex char so the sig fails validation but stays
			# the right length / character set.
			sig = ("0" if sig[0] != "0" else "1") + sig[1:]
		return {
			"X-Jarvis-Signature": sig,
			"X-Jarvis-Nonce": nonce,
			"X-Jarvis-Timestamp": str(ts),
		}

	def setUp(self):
		super().setUp()
		# Clear nonce-dedup keys from a previous test in the same class.
		# plugin_auth.py writes via raw redis-py SET NX (unnamespaced)
		# so we must delete via the raw redis method, not delete_value.
		cache = frappe.cache()
		for nonce in (
			"deadbeefdeadbeefdeadbeef",
			"oldtsnonce12345678",
			"badsignonce123456789",
			"replaynonce1234567890",
		):
			try:
				cache.delete(f"jarvis:plugin_nonce:{self.SESSION_KEY}:{nonce}")
			except Exception:
				pass

	def test_valid_signature_accepted(self):
		body = b'{"tool":"get_schema","args":{"doctype":"Customer"}}'
		extra = self._signed_headers(body=body)
		result = self._call(extra_headers=extra, body=body)
		self.assertTrue(result["ok"], msg=result)

	def test_partial_signature_headers_rejected_with_400(self):
		"""sig present but nonce missing is a client bug or downgrade
		attempt; either way, reject."""
		body = b'{"tool":"x"}'
		extra = self._signed_headers(body=body)
		del extra["X-Jarvis-Nonce"]
		result = self._call(extra_headers=extra, body=body)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "InvalidArgumentError")
		self.assertIn("partial signature", result["error"]["message"].lower())

	def test_old_timestamp_rejected(self):
		"""A captured-and-replayed request from 10 minutes ago must
		fail the timestamp skew window."""
		import time
		body = b'{}'
		extra = self._signed_headers(body=body,
		                              ts=int(time.time()) - 600,
		                              nonce="oldtsnonce12345678")
		result = self._call(extra_headers=extra, body=body)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "AuthenticationError")

	def test_bad_signature_rejected(self):
		body = b'{"tool":"get_schema","args":{"doctype":"Customer"}}'
		extra = self._signed_headers(body=body, bad_sig=True,
		                              nonce="badsignonce123456789")
		result = self._call(extra_headers=extra, body=body)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "AuthenticationError")

	def test_replayed_nonce_rejected(self):
		"""Same nonce used twice within the 120s TTL must fail the
		second time even if everything else is valid."""
		body = b'{"tool":"get_schema","args":{"doctype":"Customer"}}'
		extra = self._signed_headers(body=body,
		                              nonce="replaynonce1234567890")
		# First call: accepted (and the nonce is consumed).
		result = self._call(extra_headers=extra, body=body)
		self.assertTrue(result["ok"], msg=result)
		# Second call with SAME headers: rejected with 401.
		result = self._call(extra_headers=extra, body=body)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "AuthenticationError")
		self.assertIn("nonce", result["error"]["message"].lower())
