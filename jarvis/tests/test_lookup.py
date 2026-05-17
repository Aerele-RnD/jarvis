"""Tests for jarvis.api.lookup_user_by_session.

Tests the auth, validation, and happy-path behaviour of the endpoint that the
jarvis-openclaw-plugin's before_tool_call hook calls to resolve a sessionKey
to a Frappe user.
"""

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.api import lookup_user_by_session
from jarvis._http import raw_json_response

_TOKEN = "test-lookup-gateway-secret-xyz"
DOCTYPE = "Jarvis Chat Session"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_token(token: str):
    settings = frappe.get_single("Jarvis Settings")
    settings.db_set("openclaw_gateway_token", token)
    frappe.db.commit()


def _clear_token():
    settings = frappe.get_single("Jarvis Settings")
    settings.db_set("openclaw_gateway_token", "")
    frappe.db.commit()


def _auth_headers(token: str = _TOKEN) -> dict:
    return {"X-Jarvis-Token": token}


def _make_request(headers: dict | None = None, json_body: dict | None = None):
    req = MagicMock()
    req.method = "POST"
    req.headers = headers or {}
    if json_body is not None:
        req.get_json = MagicMock(return_value=json_body)
    else:
        req.get_json = MagicMock(return_value=None)
    return req


def _unwrap(resp) -> tuple[int, dict]:
    """Return (status_code, body_dict) from a WerkzeugResponse."""
    from werkzeug.wrappers import Response as WerkzeugResponse
    if isinstance(resp, WerkzeugResponse):
        return resp.status_code, json.loads(resp.get_data(as_text=True))
    return 200, resp


def _insert_session(session_key: str, user: str = "Administrator") -> str:
    doc = frappe.get_doc({"doctype": DOCTYPE, "session_key": session_key, "user": user})
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


def _cleanup(session_key: str) -> None:
    names = frappe.get_all(DOCTYPE, filters={"session_key": session_key}, pluck="name")
    for name in names:
        frappe.delete_doc(DOCTYPE, name, ignore_permissions=True, force=True)
    frappe.db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLookupUserBySession(FrappeTestCase):
    def setUp(self):
        super().setUp()
        _set_token(_TOKEN)

    def tearDown(self):
        super().tearDown()
        _clear_token()

    # --- Auth ---

    def test_wrong_token_returns_401(self):
        req = _make_request(
            headers=_auth_headers("wrong-token"),
            json_body={"session_key": "any"},
        )
        with patch("frappe.request", req):
            resp = lookup_user_by_session()
        status, body = _unwrap(resp)
        self.assertEqual(status, 401)
        self.assertEqual(body, {"error": "unauthorized"})

    def test_missing_token_returns_401(self):
        req = _make_request(headers={}, json_body={"session_key": "any"})
        with patch("frappe.request", req):
            resp = lookup_user_by_session()
        status, body = _unwrap(resp)
        self.assertEqual(status, 401)
        self.assertEqual(body, {"error": "unauthorized"})

    # --- Validation ---

    def test_missing_session_key_returns_400(self):
        req = _make_request(headers=_auth_headers(), json_body={})
        with patch("frappe.request", req):
            resp = lookup_user_by_session()
        status, body = _unwrap(resp)
        self.assertEqual(status, 400)
        self.assertIn("session_key", body.get("error", ""))

    def test_invalid_json_returns_400(self):
        req = _make_request(headers=_auth_headers(), json_body=None)
        with patch("frappe.request", req):
            resp = lookup_user_by_session()
        status, body = _unwrap(resp)
        self.assertEqual(status, 400)

    # --- Not found ---

    def test_unknown_session_returns_404(self):
        req = _make_request(
            headers=_auth_headers(),
            json_body={"session_key": "definitely-not-in-db-xyz"},
        )
        with patch("frappe.request", req):
            resp = lookup_user_by_session()
        status, body = _unwrap(resp)
        self.assertEqual(status, 404)
        self.assertEqual(body, {"error": "unknown session"})

    # --- Happy path ---

    def test_happy_path_returns_user(self):
        """Insert a Chat Session row → endpoint returns the correct user."""
        key = "test-lookup-session-happy-1"
        _cleanup(key)
        try:
            _insert_session(key, "Administrator")
            req = _make_request(
                headers=_auth_headers(),
                json_body={"session_key": key},
            )
            with patch("frappe.request", req):
                resp = lookup_user_by_session()
            status, body = _unwrap(resp)
            self.assertEqual(status, 200)
            self.assertEqual(body, {"user": "Administrator"})
        finally:
            _cleanup(key)

    def test_happy_path_returns_correct_user_not_another(self):
        """Lookup is scoped to the correct session_key."""
        key_a = "test-lookup-session-user-a"
        key_b = "test-lookup-session-user-b"
        _cleanup(key_a)
        _cleanup(key_b)

        # We only need one non-Administrator user — use Guest which always exists
        try:
            _insert_session(key_a, "Administrator")
            # Do NOT insert key_b — it should come back 404
            req = _make_request(
                headers=_auth_headers(),
                json_body={"session_key": key_b},
            )
            with patch("frappe.request", req):
                resp = lookup_user_by_session()
            status, body = _unwrap(resp)
            self.assertEqual(status, 404)
        finally:
            _cleanup(key_a)
            _cleanup(key_b)
