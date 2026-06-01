#!/usr/bin/env python3
"""Codex/Gemini OAuth helper — runs on the customer's laptop.

Fetched and executed via:
  curl -sSL <bench>/codex-login | \\
    JARVIS_BENCH=<bench> JARVIS_NONCE=<n> JARVIS_PROVIDER=<openai|gemini> python3

Performs RFC 6749 authorization-code + PKCE flow against the provider,
catches the redirect on http://localhost:1455/auth/callback, exchanges
the code for tokens, then POSTs the OAuthCredential blob to the bench's
receive_blob endpoint identified by the nonce.

Zero non-stdlib dependencies. Python 3.9+.
"""
import base64
import hashlib
import secrets


def generate_pkce() -> tuple[str, str]:
	"""Return (code_verifier, code_challenge) per RFC 7636."""
	verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
	challenge = base64.urlsafe_b64encode(
		hashlib.sha256(verifier.encode()).digest()
	).rstrip(b"=").decode()
	return verifier, challenge
