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


from urllib.parse import urlencode

PROVIDERS = {
	"openai": {
		"authorize": "https://auth.openai.com/oauth/authorize",
		"token":     "https://auth.openai.com/oauth/token",
		"userinfo":  "https://api.openai.com/v1/userinfo",
		"client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
		"scope":     "openid email profile offline_access",
		"openclaw_provider": "openai-codex",
		"extra_authorize_params": {},
	},
	"gemini": {
		"authorize": "https://accounts.google.com/o/oauth2/v2/auth",
		"token":     "https://oauth2.googleapis.com/token",
		"userinfo":  None,  # email comes from the id_token JWT claim
		"client_id": "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com",
		"scope":     "openid email profile https://www.googleapis.com/auth/generative-language",
		"openclaw_provider": "google-gemini-cli",
		"extra_authorize_params": {"access_type": "offline", "prompt": "consent"},
	},
}


def build_authorize_url(*, provider: str, redirect_uri: str,
                        code_challenge: str, state: str) -> str:
	if provider not in PROVIDERS:
		raise ValueError(f"unknown provider {provider!r}")
	p = PROVIDERS[provider]
	params = {
		"response_type": "code",
		"client_id": p["client_id"],
		"redirect_uri": redirect_uri,
		"scope": p["scope"],
		"code_challenge": code_challenge,
		"code_challenge_method": "S256",
		"state": state,
	}
	params.update(p["extra_authorize_params"])
	return f"{p['authorize']}?{urlencode(params)}"


def pack_blob(*, provider: str, access_token: str, refresh_token: str,
              expires_in: int, email: str, now_ts: int) -> dict:
	p = PROVIDERS[provider]
	return {
		"type": "oauth",
		"provider": p["openclaw_provider"],
		"access": access_token,
		"refresh": refresh_token or "",
		"expires": (now_ts + int(expires_in)) * 1000,
		"email": email or "",
		"clientId": p["client_id"],
	}
