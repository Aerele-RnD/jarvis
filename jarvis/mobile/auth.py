"""Mobile-app authentication + pairing helpers.

Onboarding (issue #224): the phone scans a QR shown in the Jarvis web app to
learn the *site connection details* (no typing a workspace URL), then signs in
with email + password once. That login establishes a short-lived cookie session
purely to call `get_mobile_token`, which returns a durable API key/secret; from
then on the app authenticates every request (and the realtime socket) with
`Authorization: token key:secret` — stateless, no idle-timeout. The password is
never stored; on logout the phone re-signs-in (the site is remembered).

`get_mobile_token` is idempotent: if the user already has an api_key/api_secret
it returns the EXISTING pair (decrypted) and does NOT rotate it, so a user's
existing API integrations keep working. Keys are only generated when missing.
This differs from frappe.core.doctype.user.user.generate_keys, which is
System-Manager gated AND rotates the secret on every call.
"""

import json
import socket
from base64 import b64encode
from io import BytesIO
from urllib.parse import urlparse

import frappe

# Bumped if the QR payload shape changes so old app builds can reject it cleanly.
PAIRING_PAYLOAD_VERSION = 1


@frappe.whitelist(methods=["POST"])
def get_mobile_token() -> dict:
	"""Return the logged-in user's durable api_key/api_secret (creating them only
	if absent — never rotating an existing secret).

	Returns the plaintext secret so the phone can store it. Only ever acts on the
	session user, never an arbitrary `user` argument. Also returns `site` (the
	real Frappe site name) so the client targets the realtime namespace correctly
	when the workspace is reached via a bare IP.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		raise frappe.AuthenticationError

	# PART 4 REVISED, TASK 41: a Website/portal user has no legitimate use for the
	# Jarvis mobile app's token endpoint (PART 1 TASK 6: portal users are a
	# lower-trust population, and Frappe's own generate_keys is SM-gated). This
	# stays session-user-only + idempotent, but refuses a non-Desk user
	# self-minting a durable credential here.
	from jarvis.permissions import is_system_user
	if not is_system_user(user):
		frappe.throw(
			"The Jarvis mobile token is available to Jarvis app (Desk) users only.",
			frappe.PermissionError,
		)

	doc = frappe.get_doc("User", user)
	existing_secret = doc.get_password("api_secret", raise_exception=False) if doc.api_key else None

	if doc.api_key and existing_secret:
		# Reuse — rotating would break the user's existing API integrations.
		secret = existing_secret
	else:
		secret = frappe.generate_hash(length=15)
		if not doc.api_key:
			doc.api_key = frappe.generate_hash(length=15)
		doc.api_secret = secret
		doc.save(ignore_permissions=True)

	return {"api_key": doc.api_key, "api_secret": secret, "site": frappe.local.site}


def _lan_ip() -> str | None:
	"""Best-effort primary LAN IP of this host (opens a UDP socket, sends nothing)."""
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		try:
			s.connect(("8.8.8.8", 80))
			return s.getsockname()[0]
		finally:
			s.close()
	except Exception:
		return None


def _pairing_payload() -> dict:
	"""Non-secret site connection details the phone needs to reach this site."""
	dev = bool(frappe.conf.get("developer_mode"))
	# In dev/self-host the realtime server listens on its own port; in production
	# it rides the site origin, so no port is advertised.
	port = frappe.conf.get("socketio_port") if dev else None

	site = frappe.utils.get_url()
	# Dev foolproofing: if the web was opened at localhost/.localhost/127.0.0.1,
	# the phone can't reach that host — swap in the laptop's LAN IP so the scanned
	# URL is reachable. Dev-only; production hostnames are never touched.
	if dev:
		parsed = urlparse(site)
		host = parsed.hostname or ""
		if host in ("127.0.0.1", "localhost") or host.endswith(".localhost"):
			lan = _lan_ip()
			if lan:
				suffix = f":{parsed.port}" if parsed.port else ""
				site = f"{parsed.scheme}://{lan}{suffix}"

	return {
		"v": PAIRING_PAYLOAD_VERSION,
		"site": site,
		"name": frappe.local.site,
		"port": port,
		# The web user's login id, so the phone can prefill the email field
		# (they still type their password). Not a secret.
		"email": frappe.session.user,
	}


@frappe.whitelist()
def get_pairing_qr() -> dict:
	"""Return an SVG QR (base64) encoding the site connection details, plus the
	raw payload. Shown in the Jarvis web app for the phone to scan during
	onboarding. Contains NO secret — only where to reach the site."""
	if not frappe.session.user or frappe.session.user == "Guest":
		raise frappe.AuthenticationError

	from pyqrcode import create as qrcreate

	payload = _pairing_payload()
	data = json.dumps(payload, separators=(",", ":"))

	qr = qrcreate(data, error="M")
	stream = BytesIO()
	try:
		qr.svg(stream, scale=5, quiet_zone=2, background="#ffffff", module_color="#111111")
		svg_b64 = b64encode(stream.getvalue()).decode()
	finally:
		stream.close()

	return {"svg": svg_b64, "payload": payload}
