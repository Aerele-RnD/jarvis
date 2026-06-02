"""Chat-device pairing + signing helpers.

Owns the customer-side half of openclaw's device-paired auth:
- Generates an Ed25519 keypair on first chat, persists it in Jarvis Settings.
- Calls admin's pair_chat_device endpoint to register the public side with the
  customer's openclaw container; persists the returned bearer token.
- Builds and signs the v3 device-auth payload openclaw verifies at every WS
  connect (mirrors openclaw src/gateway/device-auth.ts:36).

The keypair never leaves this bench. Admin only ever sees the public key.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

import frappe
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from jarvis import admin_client
from jarvis.exceptions import OpenclawUnreachableError


@dataclass(frozen=True)
class ChatDeviceCredentials:
	device_id: str
	public_key: str            # base64url, no padding
	private_key: Ed25519PrivateKey
	device_token: str          # bearer for auth.deviceToken at connect


def _b64u(raw: bytes) -> str:
	return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
	pad = "=" * (-len(s) % 4)
	return base64.urlsafe_b64decode(s + pad)


def _derive_device_id(public_key_raw: bytes) -> str:
	"""Mirrors openclaw's deriveDeviceIdFromPublicKey (sha256 hex)."""
	return hashlib.sha256(public_key_raw).hexdigest()


def _generate_keypair() -> tuple[Ed25519PrivateKey, bytes, str, str]:
	"""Returns (private_key, public_key_raw, public_key_b64u, device_id)."""
	priv = Ed25519PrivateKey.generate()
	pub_raw = priv.public_key().public_bytes(
		encoding=serialization.Encoding.Raw,
		format=serialization.PublicFormat.Raw,
	)
	return priv, pub_raw, _b64u(pub_raw), _derive_device_id(pub_raw)


def _load_private_key(b64u: str) -> Ed25519PrivateKey:
	return Ed25519PrivateKey.from_private_bytes(_b64u_decode(b64u))


def _save_credentials(*, settings_doc, private_key_b64u: str, public_key_b64u: str,
					  device_id: str, device_token: str) -> None:
	settings_doc.db_set("chat_device_id", device_id)
	settings_doc.db_set("chat_device_public_key", public_key_b64u)
	settings_doc.db_set("chat_device_private_key", private_key_b64u)
	settings_doc.db_set("chat_device_token", device_token)
	frappe.db.commit()


def _read_credentials() -> ChatDeviceCredentials | None:
	"""Load creds from Jarvis Settings, or None if any field is missing.

	Each piece must be present for the pairing to be usable; treating a
	partial state as 'not paired' so the next chat triggers a fresh
	pair_chat_device call and overwrites everything atomically."""
	s = frappe.get_single("Jarvis Settings")
	device_id = (s.chat_device_id or "").strip()
	public_key = (s.chat_device_public_key or "").strip()
	private_key_b64u = (s.get_password("chat_device_private_key", raise_exception=False) or "").strip()
	device_token = (s.get_password("chat_device_token", raise_exception=False) or "").strip()
	if not (device_id and public_key and private_key_b64u and device_token):
		return None
	try:
		priv = _load_private_key(private_key_b64u)
	except (ValueError, TypeError):
		# Corrupted private-key bytes - treat as unpaired so caller re-pairs.
		return None
	return ChatDeviceCredentials(
		device_id=device_id,
		public_key=public_key,
		private_key=priv,
		device_token=device_token,
	)


def ensure_paired() -> ChatDeviceCredentials:
	"""Return current chat device credentials, generating + registering them
	if missing. Idempotent: a fully-populated Settings row is reused as-is.

	Raises OpenclawUnreachableError if pairing fails (no creds to fall back
	to - the caller has no way to chat without them, so we surface the error
	cleanly instead of half-persisting an unusable state)."""
	existing = _read_credentials()
	if existing is not None:
		return existing

	priv, _pub_raw, pub_b64u, device_id = _generate_keypair()
	priv_b64u = _b64u(priv.private_bytes(
		encoding=serialization.Encoding.Raw,
		format=serialization.PrivateFormat.Raw,
		encryption_algorithm=serialization.NoEncryption(),
	))

	try:
		resp = admin_client.pair_chat_device(public_key=pub_b64u, device_id=device_id)
	except Exception as e:
		raise OpenclawUnreachableError(f"chat device pairing failed: {e}") from e

	device_token = (resp or {}).get("device_token") or ""
	if not device_token:
		raise OpenclawUnreachableError("admin pair_chat_device returned no device_token")

	settings = frappe.get_single("Jarvis Settings")
	_save_credentials(
		settings_doc=settings,
		private_key_b64u=priv_b64u,
		public_key_b64u=pub_b64u,
		device_id=device_id,
		device_token=device_token,
	)
	return ChatDeviceCredentials(
		device_id=device_id, public_key=pub_b64u,
		private_key=priv, device_token=device_token,
	)


def clear_credentials() -> None:
	"""Wipe persisted chat-device creds. Called when openclaw rejects an
	existing pairing (token revoked, device not paired, etc.) so the next
	chat attempt regenerates."""
	settings = frappe.get_single("Jarvis Settings")
	for field in ("chat_device_id", "chat_device_public_key",
				  "chat_device_private_key", "chat_device_token"):
		settings.db_set(field, "")
	frappe.db.commit()


def _normalize_metadata(value: str) -> str:
	"""Mirrors openclaw's normalizeDeviceMetadataForAuth: trim + ASCII lowercase
	(only [A-Z] → [a-z]; Unicode left alone, matching the deterministic
	cross-runtime normalization the gateway uses)."""
	trimmed = (value or "").strip()
	return "".join(c.lower() if "A" <= c <= "Z" else c for c in trimmed)


def build_payload_v3(
	*, device_id: str, client_id: str, client_mode: str, role: str,
	scopes: list[str], signed_at_ms: int, device_token: str, nonce: str,
	platform: str = "linux", device_family: str = "",
) -> str:
	"""Byte-for-byte mirror of openclaw's buildDeviceAuthPayloadV3.

	If openclaw rev-bumps the payload format we discover it as a
	'device-signature' rejection on connect - the only fragile spot in
	the whole transport rewrite, hence the explicit comment + the
	corresponding test in tests/test_chat_device.py."""
	return "|".join([
		"v3",
		device_id,
		client_id,
		client_mode,
		role,
		",".join(scopes),
		str(signed_at_ms),
		device_token or "",
		nonce,
		_normalize_metadata(platform),
		_normalize_metadata(device_family),
	])


def sign_payload(private_key: Ed25519PrivateKey, payload: str) -> str:
	"""Ed25519-sign UTF-8 payload bytes; return base64url-no-padding signature."""
	sig = private_key.sign(payload.encode("utf-8"))
	return _b64u(sig)
