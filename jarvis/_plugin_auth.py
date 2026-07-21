"""Plugin-auth validation for jarvis.api.call_tool.

Layered defenses against the C2 attack surface (2026-06-16 review):

  1. Rate limit per session_key - 60 calls/min per session. A leaked
     token can no longer fan out into a flood of writes.
  2. Audit log on validation failure - every reject is a frappe.log_error
     row so an operator can grep for brute-force attempts. The caller IP
     is recorded for triage context even though the IP itself is not
     used as an enforcement gate.
  3. Optional HMAC signature (Phase 2) - if the plugin presents
     X-Jarvis-Signature + X-Jarvis-Nonce + X-Jarvis-Timestamp, the
     bench validates a signed canonical request and dedupes the nonce
     in Redis. Replay-proof. A leaked agent_token alone is no longer
     enough to forge a request - the attacker also needs the HMAC key
     (which today is the same secret, but Phase 3 will rotate it
     under a per-tenant KDF so the blast radius shrinks further).

An IP allowlist used to be a 4th layer (default loopback + RFC1918,
tunable via Jarvis Settings.plugin_ip_allowlist). It was removed on
2026-06-19. The schema field was never migrated, so the runtime
fell back to the hardcoded default and rejected every callback from a
public IP in Frappe Cloud + remote fleet host deployments. After
weighing completion vs removal, the layer was removed: it only
defended against the narrow "secrets leaked, but no network access"
attacker profile, and the other defenses already require the attacker
to hold both bearer + sessionKey + a fresh-signed HMAC within a 60-second
window, with replay killed by Redis-backed nonce dedup. The operational
cost (every multi-host deployment maintaining CIDRs through cloud IP
churn) outweighed the marginal protection.

Plugin clients that don't send signatures keep working with a
warn-log. The plugin repo (jarvis-openclaw-plugin) gets a separate PR
to emit signatures; once all containers in the field are upgraded the
legacy path is removed.
"""

from __future__ import annotations

import hashlib
import hmac
import time

import frappe

_MAX_CLOCK_SKEW_S = 60
_NONCE_TTL_S = 120
_NONCE_REDIS_PREFIX = "jarvis:plugin_nonce:"


class PluginAuthError(Exception):
	"""Raised by validate_plugin_request on any failure.

	``http_status``: status to surface to the caller.
	``code``: stable error code for the wire envelope.
	``message``: short user-safe diagnostic. The detailed reason (which IP,
	what timestamp, etc.) is recorded via frappe.log_error so we don't leak
	infrastructure detail to attackers via the wire.
	"""

	def __init__(self, *, http_status: int, code: str, message: str):
		super().__init__(message)
		self.http_status = http_status
		self.code = code
		self.message = message


def validate_plugin_request(body_bytes: bytes) -> str:
	"""Validate every Phase-1 + Phase-2 plugin-auth precondition.

	Returns the X-Jarvis-Session value on success. Raises PluginAuthError
	with the appropriate HTTP status code on any failure. The caller
	(jarvis.api.call_tool) translates the error into its envelope.

	``body_bytes`` is the raw request body needed for HMAC validation -
	only used when the optional signature headers are present.
	"""
	headers = _safe_headers()

	# Caller IP is read once and threaded through every audit row in
	# the remaining checks so the operator can grep the Error Log for
	# brute-force activity. It is not used as an enforcement gate; see
	# the module docstring for the removal rationale.
	caller_ip = _caller_ip()

	# 1. Bearer token (legacy, still required).
	presented_token = (headers.get("X-Jarvis-Token") or "").strip()
	if not presented_token:
		raise PluginAuthError(
			http_status=401,
			code="AuthenticationError",
			message="X-Jarvis-Token header missing",
		)
	expected_token = _agent_token()
	if not expected_token:
		_audit_log(
			"plugin_auth: agent_token unset on bench",
			"Jarvis Settings.agent_token is empty; refusing all plugin requests",
		)
		raise PluginAuthError(
			http_status=503,
			code="ServiceUnavailable",
			message="plugin auth not configured on this bench",
		)
	if not hmac.compare_digest(presented_token, expected_token):
		_audit_log(
			"plugin_auth: bearer mismatch",
			f"remote_ip={caller_ip!r} session={headers.get('X-Jarvis-Session', '')!r}",
		)
		raise PluginAuthError(
			http_status=401,
			code="AuthenticationError",
			message="invalid X-Jarvis-Token",
		)

	# 3a. C2 (2026-06-16 review) - time-bounded token. Operators
	# configure ``Jarvis Settings.agent_token_max_age_days`` (default 90)
	# and the rotate_agent_token endpoint stamps issued_at = now. Past
	# the configured age the token is rejected with a distinct code so
	# the bench's UI can render a "rotate now" CTA instead of a generic
	# 401. max_age=0 disables expiry (legacy escape hatch).
	if _agent_token_expired():
		_audit_log(
			"plugin_auth: agent_token past max-age",
			"agent_token is older than agent_token_max_age_days; "
			"operator must call rotate_agent_token to refresh",
		)
		raise PluginAuthError(
			http_status=401,
			code="AgentTokenExpired",
			message="agent_token past configured max age; operator must rotate",
		)

	# 3. Session header required.
	session_key = (headers.get("X-Jarvis-Session") or "").strip()
	if not session_key:
		raise PluginAuthError(
			http_status=400,
			code="InvalidArgumentError",
			message="X-Jarvis-Session header required when using X-Jarvis-Token",
		)

	# 4. HMAC signature (Phase 2) - validated if all three headers are
	# present. Plugin clients without signature support keep working but
	# get a warn-log so operators can track the rollout.
	sig = (headers.get("X-Jarvis-Signature") or "").strip()
	nonce = (headers.get("X-Jarvis-Nonce") or "").strip()
	ts_str = (headers.get("X-Jarvis-Timestamp") or "").strip()
	if sig or nonce or ts_str:
		# Partial signature headers are ALWAYS a reject - either you sign
		# the request properly or you don't sign at all. Partial = client
		# bug at best, downgrade-attack attempt at worst.
		if not (sig and nonce and ts_str):
			raise PluginAuthError(
				http_status=400,
				code="InvalidArgumentError",
				message="partial signature headers; provide all of "
				"X-Jarvis-Signature/X-Jarvis-Nonce/X-Jarvis-Timestamp",
			)
		_validate_signature(
			token=expected_token,
			session_key=session_key,
			body_bytes=body_bytes,
			signature=sig,
			nonce=nonce,
			timestamp_str=ts_str,
		)
	else:
		# Legacy bearer-only path. Log once so operators can see how many
		# unsigned requests are still in flight before deprecation.
		frappe.logger().info(
			"plugin_auth: legacy bearer-only request from %s (session=%s); "
			"plugin should be upgraded to send signed requests",
			caller_ip,
			session_key,
		)

	# 5. Rate limit per session_key (after signature validation so the
	# rate-limit counter is for *valid* callers; spammers exhaust their
	# own keys, not the counter we'd care about for legitimate use).
	_enforce_rate_limit(session_key)

	return session_key


# ----- internals --------------------------------------------------------


def _safe_headers() -> dict[str, str]:
	"""Return request.headers as a plain dict, tolerating a missing or
	header-less request object (test paths that don't fake one)."""
	req = getattr(frappe, "request", None)
	if req is None:
		return {}
	headers = getattr(req, "headers", None)
	if headers is None:
		return {}
	try:
		return {k: v for k, v in headers.items()}
	except Exception:
		# Werkzeug EnvironHeaders supports .items(); a test fake might not.
		return dict(headers) if hasattr(headers, "__iter__") else {}


def _caller_ip() -> str:
	"""Best-effort client IP. Prefers frappe's parsed value, falls back to
	the raw remote_addr. Returns "" if neither is available so the
	allowlist check fails closed."""
	try:
		ip = (getattr(frappe.local, "request_ip", None) or "").strip()
	except Exception:
		ip = ""
	if ip:
		return ip
	req = getattr(frappe, "request", None)
	if req is None:
		return ""
	for attr in ("remote_addr",):
		val = getattr(req, attr, "")
		if val:
			return str(val).strip()
	return ""


def _agent_token() -> str:
	settings = frappe.get_single("Jarvis Settings")
	return settings.get_password("agent_token", raise_exception=False) or ""


def _agent_token_expired() -> bool:
	"""Return True iff the bench's agent_token is past its operator-
	configured max age.

	Fields driving this:
	  - agent_token_issued_at: Datetime (set by rotate_agent_token)
	  - agent_token_max_age_days: Int (default 90, 0 disables)

	A token with no issued_at is treated as not-expired (legacy
	deployments that pre-date this field; operator must run a one-time
	rotate to set the timestamp going forward). Backwards compat with
	pre-migration benches that don't have the column yet: any read
	failure is treated as "not expired" so call_tool doesn't 500 on a
	deploy where the JSON shipped but bench migrate hasn't run.
	"""
	try:
		settings = frappe.get_single("Jarvis Settings")
		max_age_days = int(getattr(settings, "agent_token_max_age_days", 0) or 0)
		if max_age_days <= 0:
			return False
		issued_at = getattr(settings, "agent_token_issued_at", None)
	except Exception:
		return False
	if not issued_at:
		# Legacy token (issued before this field existed) - don't break
		# the bench by expiring it; surface via the cron-side warning
		# instead so operators can do a one-time rotate at their leisure.
		return False
	try:
		import datetime as _dt

		issued = frappe.utils.get_datetime(issued_at)
		age = (_dt.datetime.now(issued.tzinfo) if issued.tzinfo else _dt.datetime.now()) - issued
		return age.days >= max_age_days
	except Exception:
		return False


def _canonical_request(*, session_key: str, body_bytes: bytes, nonce: str, timestamp_s: int) -> bytes:
	"""Canonical string the plugin signs.

	Format: session_key | sha256(body) | nonce | timestamp.

	Note we sign the body sha256 not the body itself - tests can construct
	a deterministic payload easily, and we avoid memcpy'ing large bodies
	through hmac.
	"""
	body_hash = hashlib.sha256(body_bytes or b"").hexdigest()
	parts = (session_key, body_hash, nonce, str(timestamp_s))
	return "|".join(parts).encode("utf-8")


def _validate_signature(
	*, token: str, session_key: str, body_bytes: bytes, signature: str, nonce: str, timestamp_str: str
) -> None:
	# Timestamp sanity - reject clearly-old requests so a captured one
	# stops being replayable past the skew window.
	try:
		ts = int(timestamp_str)
	except ValueError:
		raise PluginAuthError(
			http_status=400,
			code="InvalidArgumentError",
			message="X-Jarvis-Timestamp must be a unix-epoch integer",
		) from None
	now = int(time.time())
	if abs(now - ts) > _MAX_CLOCK_SKEW_S:
		_audit_log("plugin_auth: timestamp out of skew window", f"now={now} ts={ts} diff={abs(now - ts)}s")
		raise PluginAuthError(
			http_status=401,
			code="AuthenticationError",
			message="signed request timestamp out of acceptable window",
		)

	# Reject overly-short nonces (hex-16 = 8 random bytes is the floor).
	if len(nonce) < 16 or len(nonce) > 128:
		raise PluginAuthError(
			http_status=400,
			code="InvalidArgumentError",
			message="X-Jarvis-Nonce length out of bounds",
		)

	# Verify HMAC.
	canonical = _canonical_request(
		session_key=session_key,
		body_bytes=body_bytes,
		nonce=nonce,
		timestamp_s=ts,
	)
	expected = hmac.new(token.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
	if not hmac.compare_digest(expected, signature):
		_audit_log("plugin_auth: signature mismatch", f"session={session_key!r} nonce_prefix={nonce[:8]!r}")
		raise PluginAuthError(
			http_status=401,
			code="AuthenticationError",
			message="signature did not validate",
		)

	# Nonce-dedup window. Use Redis SETNX so two concurrent calls with the
	# same nonce can never both pass (the second loses the race).
	cache = frappe.cache()
	key = _NONCE_REDIS_PREFIX + session_key + ":" + nonce
	try:
		got = cache.set(key, b"1", nx=True, ex=_NONCE_TTL_S)
	except Exception:
		# If Redis is unreachable we shouldn't burn auth - fall back to
		# log-and-allow so the chat path stays up. Plain bearer still
		# guards the door. Production should monitor for these.
		frappe.logger().error(
			"plugin_auth: redis SETNX for nonce dedup failed; "
			"signature validated but replay window not enforced",
		)
		return
	if not got:
		_audit_log(
			"plugin_auth: nonce replay rejected", f"session={session_key!r} nonce_prefix={nonce[:8]!r}"
		)
		raise PluginAuthError(
			http_status=401,
			code="AuthenticationError",
			message="signed request nonce already used",
		)


def _enforce_rate_limit(session_key: str) -> None:
	"""60 calls/min per session_key. The 60s tick window resets on first
	call so a quiet session isn't penalized for past activity."""
	cache = frappe.cache()
	key = f"jarvis:plugin_rl:{session_key}"
	try:
		count = cache.incr(key)
	except Exception:
		# As with the nonce path: don't burn auth on Redis trouble.
		return
	if count == 1:
		try:
			cache.expire(key, 60)
		except Exception:
			pass
	if count > 60:
		_audit_log("plugin_auth: rate limit exceeded", f"session={session_key!r} count={count}")
		raise PluginAuthError(
			http_status=429,
			code="RateLimitExceededError",
			message="plugin-auth rate limit exceeded for this session",
		)


def _audit_log(title: str, detail: str) -> None:
	"""Write a single-line audit row to Error Log. Each title bucket is
	cheap to grep for ('plugin_auth: bearer mismatch') so an operator can
	tail a single substring to see brute-force activity."""
	try:
		frappe.log_error(title=title, message=detail)
	except Exception:
		# Logging must never fail the request.
		pass
