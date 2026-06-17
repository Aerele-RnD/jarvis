"""Tests for jarvis.chat.device - chat keypair + pairing + v3 signing.

Two surface areas to cover:
1. ensure_paired: generates a keypair if missing, calls admin to register the
   public side, persists everything atomically; reuses existing creds when
   present; surfaces admin failures as OpenclawUnreachableError without
   half-persisting a broken state.
2. build_payload_v3 / sign_payload: the byte-exact mirror of openclaw's
   device-auth.ts:36 - if openclaw rev-bumps the format, this is the test
   that catches it before chat goes live.
"""

from __future__ import annotations

import base64
import hashlib
from unittest.mock import patch

import frappe
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from frappe.tests.utils import FrappeTestCase

from jarvis.chat import device as chat_device
from jarvis.exceptions import OpenclawUnreachableError


def _b64u(raw: bytes) -> str:
	return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


_SNAPSHOT_PASSWORD_FIELDS = (
	"chat_device_private_key", "chat_device_token",
)
_SNAPSHOT_PLAIN_FIELDS = (
	"chat_device_id", "chat_device_public_key",
)


class _SettingsSnapshotMixin:
	"""Save/restore the chat_device_* fields so the test suite leaves no
	residue on whichever site bench picked. Mirrors test_settings.py."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		s = frappe.get_single("Jarvis Settings")
		snap = {f: s.get(f) for f in _SNAPSHOT_PLAIN_FIELDS}
		for f in _SNAPSHOT_PASSWORD_FIELDS:
			snap[f] = s.get_password(f, raise_exception=False) or ""
		cls._chat_device_snapshot = snap

	@classmethod
	def tearDownClass(cls):
		try:
			s = frappe.get_single("Jarvis Settings")
			for f, v in cls._chat_device_snapshot.items():
				s.db_set(f, v)
			frappe.db.commit()
		finally:
			super().tearDownClass()


def _clear_settings():
	"""Wipe chat_device_* between tests so each one starts unpaired."""
	s = frappe.get_single("Jarvis Settings")
	for f in (*_SNAPSHOT_PLAIN_FIELDS, *_SNAPSHOT_PASSWORD_FIELDS):
		s.db_set(f, "")
	frappe.db.commit()


class TestEnsurePaired(_SettingsSnapshotMixin, FrappeTestCase):
	def setUp(self):
		_clear_settings()

	def test_generates_keypair_calls_admin_and_persists(self):
		captured = {}

		def _fake_pair(public_key, device_id):
			captured["public_key"] = public_key
			captured["device_id"] = device_id
			return {"device_token": "tok-from-admin"}

		with patch("jarvis.chat.device.admin_client.pair_chat_device", side_effect=_fake_pair):
			creds = chat_device.ensure_paired()

		# Returned object is internally consistent.
		self.assertEqual(creds.device_token, "tok-from-admin")
		self.assertEqual(creds.public_key, captured["public_key"])
		self.assertEqual(creds.device_id, captured["device_id"])
		# deviceId must match sha256(rawPublicKey) - same invariant openclaw enforces.
		raw = base64.urlsafe_b64decode(captured["public_key"] + "=" * (-len(captured["public_key"]) % 4))
		self.assertEqual(creds.device_id, hashlib.sha256(raw).hexdigest())
		# Persisted in Settings.
		s = frappe.get_single("Jarvis Settings")
		self.assertEqual(s.chat_device_id, creds.device_id)
		self.assertEqual(s.chat_device_public_key, creds.public_key)
		self.assertEqual(s.get_password("chat_device_token"), "tok-from-admin")
		self.assertTrue(s.get_password("chat_device_private_key"))

	def test_reuses_existing_creds_without_admin_call(self):
		# Seed Settings with a valid keypair + token.
		priv = Ed25519PrivateKey.generate()
		pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw,
												  serialization.PublicFormat.Raw)
		priv_raw = priv.private_bytes(serialization.Encoding.Raw,
									   serialization.PrivateFormat.Raw,
									   serialization.NoEncryption())
		s = frappe.get_single("Jarvis Settings")
		s.db_set("chat_device_id", hashlib.sha256(pub_raw).hexdigest())
		s.db_set("chat_device_public_key", _b64u(pub_raw))
		s.db_set("chat_device_private_key", _b64u(priv_raw))
		s.db_set("chat_device_token", "tok-existing")
		frappe.db.commit()

		with patch("jarvis.chat.device.admin_client.pair_chat_device") as mock_pair:
			creds = chat_device.ensure_paired()
		self.assertFalse(mock_pair.called)
		self.assertEqual(creds.device_token, "tok-existing")
		self.assertEqual(creds.device_id, hashlib.sha256(pub_raw).hexdigest())

	def test_admin_failure_raises_and_does_not_persist(self):
		with patch("jarvis.chat.device.admin_client.pair_chat_device",
				   side_effect=RuntimeError("boom")):
			with self.assertRaises(OpenclawUnreachableError):
				chat_device.ensure_paired()
		# Nothing persisted on failure.
		s = frappe.get_single("Jarvis Settings")
		self.assertFalse(s.chat_device_id)
		self.assertFalse(s.get_password("chat_device_private_key", raise_exception=False))

	def test_empty_device_token_raises_unreachable(self):
		with patch("jarvis.chat.device.admin_client.pair_chat_device",
				   return_value={"device_token": ""}):
			with self.assertRaises(OpenclawUnreachableError):
				chat_device.ensure_paired()

	def test_partial_state_triggers_repair(self):
		"""If only some fields are set, treat the whole pairing as missing
		so the next call re-pairs atomically - protects against half-failed
		writes from a previous deploy/migration."""
		s = frappe.get_single("Jarvis Settings")
		s.db_set("chat_device_id", "abc")
		s.db_set("chat_device_public_key", "")  # incomplete
		s.db_set("chat_device_private_key", "")
		s.db_set("chat_device_token", "")
		frappe.db.commit()

		with patch("jarvis.chat.device.admin_client.pair_chat_device",
				   return_value={"device_token": "tok-repaired"}):
			creds = chat_device.ensure_paired()
		self.assertEqual(creds.device_token, "tok-repaired")
		self.assertNotEqual(creds.device_id, "abc")  # fresh keypair was generated


class TestRotateChatDevice(_SettingsSnapshotMixin, FrappeTestCase):
	def setUp(self):
		_clear_settings()

	def test_rotate_generates_fresh_keypair_even_when_pairing_exists(self):
		# Seed Settings with valid pre-rotation creds.
		priv = Ed25519PrivateKey.generate()
		pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw,
												  serialization.PublicFormat.Raw)
		old_device_id = hashlib.sha256(pub_raw).hexdigest()
		s = frappe.get_single("Jarvis Settings")
		s.db_set("chat_device_id", old_device_id)
		s.db_set("chat_device_public_key", _b64u(pub_raw))
		s.db_set("chat_device_private_key", _b64u(priv.private_bytes(
			serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
			serialization.NoEncryption())))
		s.db_set("chat_device_token", "tok-old")
		frappe.db.commit()

		with patch("jarvis.chat.device.admin_client.pair_chat_device",
				   return_value={"device_token": "tok-new"}):
			out = chat_device.rotate_chat_device()

		# Wire-shape check + new device_id is fresh + token rotated.
		self.assertTrue(out["ok"])
		self.assertNotEqual(out["data"]["device_id"], old_device_id)
		s2 = frappe.get_single("Jarvis Settings")
		self.assertEqual(s2.chat_device_id, out["data"]["device_id"])
		self.assertEqual(s2.get_password("chat_device_token"), "tok-new")

	def test_rotate_preserves_old_creds_on_admin_failure(self):
		# Seed old creds.
		priv = Ed25519PrivateKey.generate()
		pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw,
												  serialization.PublicFormat.Raw)
		old_device_id = hashlib.sha256(pub_raw).hexdigest()
		s = frappe.get_single("Jarvis Settings")
		s.db_set("chat_device_id", old_device_id)
		s.db_set("chat_device_public_key", _b64u(pub_raw))
		s.db_set("chat_device_token", "tok-old")
		frappe.db.commit()

		with patch("jarvis.chat.device.admin_client.pair_chat_device",
				   side_effect=RuntimeError("admin down")):
			with self.assertRaises(OpenclawUnreachableError):
				chat_device.rotate_chat_device()

		# Old creds intact.
		s2 = frappe.get_single("Jarvis Settings")
		self.assertEqual(s2.chat_device_id, old_device_id)
		self.assertEqual(s2.get_password("chat_device_token"), "tok-old")


class TestSigning(FrappeTestCase):
	def test_build_payload_v3_format(self):
		out = chat_device.build_payload_v3(
			device_id="DID", client_id="gateway-client", client_mode="backend",
			role="operator", scopes=["operator.write", "operator.admin"],
			signed_at_ms=12345, device_token="TOK", nonce="NONCE",
			platform="Linux", device_family="",
		)
		# Mirror of openclaw's buildDeviceAuthPayloadV3 (device-auth.ts:36).
		# Platform is normalized to ASCII lowercase ("linux"); device_family
		# stays empty.
		expected = "v3|DID|gateway-client|backend|operator|operator.write,operator.admin|12345|TOK|NONCE|linux|"
		self.assertEqual(out, expected)

	def test_sign_payload_verifies_with_public_key(self):
		"""Round-trip: sign with private, verify with the matching public key
		using the same Ed25519 raw scheme openclaw uses."""
		priv = Ed25519PrivateKey.generate()
		pub_raw = priv.public_key().public_bytes(serialization.Encoding.Raw,
												  serialization.PublicFormat.Raw)
		payload = "v3|x|y|z|operator||0||n||"
		sig_b64u = chat_device.sign_payload(priv, payload)
		# Decode and verify.
		sig = base64.urlsafe_b64decode(sig_b64u + "=" * (-len(sig_b64u) % 4))
		pub = Ed25519PublicKey.from_public_bytes(pub_raw)
		pub.verify(sig, payload.encode("utf-8"))  # raises if invalid

	def test_metadata_normalization_lowercases_ascii_only(self):
		out = chat_device.build_payload_v3(
			device_id="x", client_id="c", client_mode="m", role="r",
			scopes=["s"], signed_at_ms=0, device_token="", nonce="n",
			platform="DarwinARM64", device_family="iPhone15",
		)
		# Trailing fields after the nonce: |<platform>|<device_family>
		self.assertTrue(out.endswith("|darwinarm64|iphone15"))
