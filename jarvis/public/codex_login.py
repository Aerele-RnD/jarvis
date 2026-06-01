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
		"scope":     "openid profile email offline_access api.connectors.read api.connectors.invoke",
		"openclaw_provider": "openai-codex",
		# Codex CLI sends these alongside the standard PKCE params; auth.openai.com
		# returns a generic "unknown_error" page if any are missing. originator
		# identifies the client to OpenAI's telemetry; the other two unlock
		# Codex's simplified browser flow against this client_id.
		"extra_authorize_params": {
			"id_token_add_organizations": "true",
			"codex_cli_simplified_flow":   "true",
			"originator":                  "codex_cli_rs",
		},
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


import json as _json


def email_from_id_token(id_token: str) -> str:
	"""Parse the email claim from a JWT's payload. No signature check —
	the channel we got this on (TLS to the provider's token endpoint) is
	the trust root."""
	if not id_token or id_token.count(".") < 2:
		return ""
	try:
		_, payload, _ = id_token.split(".", 2)
		# JWT base64url has no padding; pad to multiple of 4
		padding = "=" * (-len(payload) % 4)
		decoded = base64.urlsafe_b64decode(payload + padding)
		return _json.loads(decoded).get("email", "") or ""
	except (ValueError, _json.JSONDecodeError):
		return ""


import http.server
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

_LOOPBACK_HOST = "127.0.0.1"
_LOOPBACK_PORTS = (1455, 1457)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
	expected_state = None

	def do_GET(self):
		parsed = urllib.parse.urlparse(self.path)
		if parsed.path != "/auth/callback":
			self.send_response(404)
			self.end_headers()
			return
		q = urllib.parse.parse_qs(parsed.query)
		if q.get("state", [""])[0] != self.expected_state:
			self.send_response(400)
			self.end_headers()
			self.wfile.write(b"state mismatch")
			return
		if "error" in q:
			self.send_response(400)
			self.end_headers()
			self.wfile.write(f"oauth error: {q['error'][0]}".encode())
			self.server.captured = {"error": q["error"][0]}
			return
		self.server.captured = {"code": q.get("code", [""])[0]}
		self.send_response(200)
		self.send_header("Content-Type", "text/html; charset=utf-8")
		self.end_headers()
		self.wfile.write(
			b"<html><body style='font-family:sans-serif;text-align:center;"
			b"padding:4em'><h2>&#x2713; Connected to Jarvis</h2>"
			b"<p>You can close this tab and return to the wizard.</p>"
			b"</body></html>"
		)

	def log_message(self, *args):
		pass  # silence default access log


def _bind_loopback(expected_state: str):
	last_err = None
	for port in _LOOPBACK_PORTS:
		try:
			handler = type("H", (_CallbackHandler,), {"expected_state": expected_state})
			srv = http.server.HTTPServer((_LOOPBACK_HOST, port), handler)
			srv.captured = None
			return srv, port
		except OSError as e:
			last_err = e
	raise SystemExit(
		f"ports {_LOOPBACK_PORTS} are all occupied ({last_err}); "
		f"free one and retry."
	)


def _exchange_code(*, provider: str, code: str, code_verifier: str,
                   redirect_uri: str) -> dict:
	p = PROVIDERS[provider]
	body = urllib.parse.urlencode({
		"grant_type": "authorization_code",
		"code": code,
		"code_verifier": code_verifier,
		"client_id": p["client_id"],
		"redirect_uri": redirect_uri,
	}).encode()
	req = urllib.request.Request(p["token"], data=body, method="POST")
	req.add_header("Content-Type", "application/x-www-form-urlencoded")
	try:
		with urllib.request.urlopen(req, timeout=30) as resp:
			return _json.loads(resp.read())
	except urllib.error.HTTPError as e:
		raise SystemExit(
			f"token exchange failed: HTTP {e.code} {e.reason}: "
			f"{e.read().decode(errors='replace')}"
		)


def _fetch_userinfo_email(provider: str, access_token: str) -> str:
	p = PROVIDERS[provider]
	if not p["userinfo"]:
		return ""
	req = urllib.request.Request(p["userinfo"])
	req.add_header("Authorization", f"Bearer {access_token}")
	try:
		with urllib.request.urlopen(req, timeout=15) as resp:
			return _json.loads(resp.read()).get("email", "") or ""
	except (urllib.error.URLError, ValueError):
		return ""


def _post_blob(bench_url: str, nonce: str, blob: dict):
	url = (
		bench_url.rstrip("/")
		+ "/api/method/jarvis.oauth.api.receive_blob"
		+ f"?nonce={urllib.parse.quote(nonce)}"
	)
	body = _json.dumps({"blob": blob}).encode()
	req = urllib.request.Request(url, data=body, method="POST")
	req.add_header("Content-Type", "application/json")
	try:
		with urllib.request.urlopen(req, timeout=30) as resp:
			return _json.loads(resp.read())
	except urllib.error.HTTPError as e:
		raise SystemExit(
			f"bench rejected blob: HTTP {e.code} {e.reason}: "
			f"{e.read().decode(errors='replace')}"
		)


def _validate_bench_url(url: str):
	parsed = urllib.parse.urlparse(url)
	if parsed.scheme == "https":
		return
	# Plain HTTP is only permitted for loopback. RFC 6761 reserves
	# .localhost (and anything ending in it) for local resolution, so
	# bench sites like jarvis.localhost / jarvis-test.localhost qualify.
	host = (parsed.hostname or "").lower()
	if parsed.scheme == "http" and (
		host == "127.0.0.1" or host == "localhost" or host.endswith(".localhost")
	):
		return
	raise SystemExit(
		f"JARVIS_BENCH must be https:// (or http://*.localhost / 127.0.0.1 for local-dev). Got: {url}"
	)


def main():
	bench = os.environ.get("JARVIS_BENCH", "").strip()
	nonce = os.environ.get("JARVIS_NONCE", "").strip()
	provider = os.environ.get("JARVIS_PROVIDER", "").strip().lower()
	if not bench or not nonce or not provider:
		print("error: JARVIS_BENCH, JARVIS_NONCE, JARVIS_PROVIDER all required",
		      file=sys.stderr)
		sys.exit(2)
	if provider not in PROVIDERS:
		print(f"error: unknown JARVIS_PROVIDER={provider!r}; want openai or gemini",
		      file=sys.stderr)
		sys.exit(2)
	_validate_bench_url(bench)

	verifier, challenge = generate_pkce()
	state = secrets.token_urlsafe(16)

	srv, port = _bind_loopback(state)
	redirect_uri = f"http://{_LOOPBACK_HOST}:{port}/auth/callback"

	url = build_authorize_url(
		provider=provider, redirect_uri=redirect_uri,
		code_challenge=challenge, state=state,
	)
	print(f"→ Opening browser to authorize with {provider}…")
	print(f"  (If your browser doesn't open, paste this URL: {url})")
	webbrowser.open(url)

	t = threading.Thread(target=srv.serve_forever, daemon=True)
	t.start()
	# Wait up to 10 minutes for the redirect
	deadline = time.time() + 600
	while srv.captured is None and time.time() < deadline:
		time.sleep(0.2)
	srv.shutdown()

	if srv.captured is None:
		print("error: timed out waiting for authorization (10 min)", file=sys.stderr)
		sys.exit(4)
	if "error" in srv.captured:
		print(f"error: sign-in cancelled ({srv.captured['error']})", file=sys.stderr)
		sys.exit(4)

	print("→ Exchanging code for tokens…")
	tokens = _exchange_code(
		provider=provider, code=srv.captured["code"],
		code_verifier=verifier, redirect_uri=redirect_uri,
	)
	email = tokens.get("account_email") or ""
	if not email:
		if provider == "openai":
			email = _fetch_userinfo_email(provider, tokens["access_token"])
		else:
			email = email_from_id_token(tokens.get("id_token", ""))

	blob = pack_blob(
		provider=provider,
		access_token=tokens["access_token"],
		refresh_token=tokens.get("refresh_token") or "",
		expires_in=int(tokens.get("expires_in", 3600)),
		email=email,
		now_ts=int(time.time()),
	)
	print("→ Sending credential to Jarvis bench…")
	_post_blob(bench, nonce, blob)
	print("✓ Done. You can close this terminal.")


if __name__ == "__main__":
	main()
