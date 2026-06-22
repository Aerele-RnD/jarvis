"""Self-hosted (bring-your-own) openclaw connection.

Lets a customer point this bench at their own openclaw server instead of an
Aerele-managed container. The customer brings their own openclaw + their own
LLM; Aerele's persona/skills and managed hosting stay on the Managed path.

Transport: self-hosted chat uses openclaw's HTTP OpenAI-compatible surface
(``POST {base}/v1/chat/completions`` with ``Authorization: Bearer <token>``),
which openclaw grants full operator scope for shared-secret bearer auth - so
no Ed25519 device-pairing is needed (unlike the WS path, which strips
operator.write from non-loopback token-only clients). See the design spec
``docs/superpowers/specs/2026-06-18-self-hosted-openclaw-design.md``.

v1 = connect + chat. ERP tools (the openclaw plugin) are out of scope.
"""

from __future__ import annotations

import json

import frappe
import requests
from frappe.utils import now_datetime

# Timeouts (seconds). Reachability is snappy; the deep chat ping tolerates a
# slow reasoning model.
_REACHABLE_TIMEOUT = 8
_AUTH_TIMEOUT = 20
_DEEP_TIMEOUT = 120


def _normalize_base_url(raw: str) -> str:
    """Return an http(s) base URL with no trailing slash.

    Accepts ws:// / wss:// (managed-style) and converts to http/https so an
    operator pasting a gateway URL still works. Raises ValueError on a shape
    we can't use."""
    url = (raw or "").strip().rstrip("/")
    if not url:
        raise ValueError("openclaw URL is empty")
    if url.startswith("ws://"):
        url = "http://" + url[len("ws://"):]
    elif url.startswith("wss://"):
        url = "https://" + url[len("wss://"):]
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError(
            f"openclaw URL must start with http(s):// (or ws(s)://), got {raw!r}"
        )
    return url


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"check": name, "ok": bool(ok), "detail": detail}


def validate_connection(base_url: str, token: str, *, deep: bool = False) -> dict:
    """Run pre-connect checks against a self-hosted openclaw.

    Pure HTTP, token-only - no device pairing. Never raises for a *failed
    check*; it returns a structured result so the UI can show exactly what's
    wrong. Returns::

        {"ok": bool,                 # True iff all REQUIRED checks pass
         "checks": [{check, ok, detail}, ...],
         "openclaw_version": str | None,
         "models": [str, ...]}

    Required checks: url_shape, reachable, auth, llm_ready. ``deep`` adds an
    actual chat round-trip (slow; costs an LLM call) but is not required to
    pass for ``ok``.
    """
    checks: list[dict] = []
    version: str | None = None
    models: list[str] = []

    # 1. URL shape
    try:
        base = _normalize_base_url(base_url)
        checks.append(_check("url_shape", True, base))
    except ValueError as e:
        checks.append(_check("url_shape", False, str(e)))
        return {"ok": False, "checks": checks, "openclaw_version": None, "models": []}

    headers = {"Authorization": f"Bearer {(token or '').strip()}"}

    # 2. Reachable (unauthenticated health endpoint)
    try:
        r = requests.get(f"{base}/healthz", timeout=_REACHABLE_TIMEOUT)
        checks.append(_check(
            "reachable", r.status_code == 200,
            f"GET /healthz -> HTTP {r.status_code}",
        ))
    except requests.RequestException as e:
        checks.append(_check("reachable", False, f"GET /healthz failed: {e}"))
        return {"ok": False, "checks": checks, "openclaw_version": version, "models": models}

    # 3 + 4. Auth + LLM-ready via the OpenAI-compatible models list.
    try:
        r = requests.get(f"{base}/v1/models", headers=headers, timeout=_AUTH_TIMEOUT)
        if r.status_code in (401, 403):
            checks.append(_check("auth", False, f"GET /v1/models -> HTTP {r.status_code} (bad token)"))
            checks.append(_check("llm_ready", False, "skipped (auth failed)"))
            return {"ok": False, "checks": checks, "openclaw_version": version, "models": models}
        if r.status_code != 200:
            checks.append(_check("auth", False, f"GET /v1/models -> HTTP {r.status_code}"))
            checks.append(_check("llm_ready", False, "skipped (models endpoint not OK)"))
            return {"ok": False, "checks": checks, "openclaw_version": version, "models": models}
        checks.append(_check("auth", True, "bearer token accepted"))
        try:
            data = r.json().get("data") or []
            models = [m.get("id") for m in data if isinstance(m, dict) and m.get("id")]
        except (ValueError, AttributeError):
            models = []
        checks.append(_check(
            "llm_ready", bool(models),
            f"{len(models)} model(s) available" if models else "no models listed (configure an LLM on your openclaw)",
        ))
    except requests.RequestException as e:
        checks.append(_check("auth", False, f"GET /v1/models failed: {e}"))
        checks.append(_check("llm_ready", False, "skipped (request failed)"))
        return {"ok": False, "checks": checks, "openclaw_version": version, "models": models}

    # 5. Optional deep test: a real (tiny) chat round-trip.
    if deep:
        try:
            r = requests.post(
                f"{base}/v1/chat/completions", headers=headers,
                json={"model": "openclaw",
                      "messages": [{"role": "user", "content": "ping"}],
                      "stream": False},
                timeout=_DEEP_TIMEOUT,
            )
            reply = ""
            if r.status_code == 200:
                try:
                    reply = ((r.json().get("choices") or [{}])[0]
                             .get("message", {}).get("content") or "").strip()
                except (ValueError, AttributeError, IndexError):
                    reply = ""
            checks.append(_check(
                "deep_chat", r.status_code == 200 and bool(reply),
                f"chat/completions -> HTTP {r.status_code}"
                + (f", reply {len(reply)} chars" if reply else ", empty/failed reply"),
            ))
        except requests.RequestException as e:
            checks.append(_check("deep_chat", False, f"chat/completions failed: {e}"))

    required = {"url_shape", "reachable", "auth", "llm_ready"}
    ok = all(c["ok"] for c in checks if c["check"] in required)
    return {"ok": ok, "checks": checks, "openclaw_version": version, "models": models}


@frappe.whitelist()
def test_connection(base_url: str, token: str = "", deep: int | str = 0) -> dict:
    """UI 'Test connection' button. System Manager only (reads/writes config)."""
    frappe.only_for("System Manager")
    deep_flag = str(deep) in ("1", "true", "True")
    # Fall back to the stored token if the UI sends a blank (masked Password field).
    if not (token or "").strip():
        token = (frappe.get_single("Jarvis Settings").get_password(
            "agent_token", raise_exception=False) or "")
    return validate_connection(base_url, token, deep=deep_flag)


@frappe.whitelist()
def save_self_hosted(base_url: str, token: str, deep: int | str = 0,
                     stream: int | str = 1) -> dict:
    """Validate, then switch this bench to Self-Hosted mode pointed at the
    given openclaw. Refuses to persist if validation fails (no half-config).

    ``stream`` controls token-by-token SSE rendering of the agent's reply
    (default on; off => one-shot, for openclaw behind a buffering proxy).

    System Manager only."""
    frappe.only_for("System Manager")
    deep_flag = str(deep) in ("1", "true", "True")
    result = validate_connection(base_url, token, deep=deep_flag)
    if not result["ok"]:
        return {"ok": False, "error": "validation_failed", "result": result}

    base = _normalize_base_url(base_url)
    s = frappe.get_single("Jarvis Settings")
    s.db_set("deployment_mode", "Self-Hosted")
    s.db_set("agent_url", base)
    s.db_set("agent_token", (token or "").strip())
    s.db_set("selfhost_stream", 1 if str(stream) in ("1", "true", "True") else 0)
    s.db_set("selfhost_last_validated_at", now_datetime())
    s.db_set("selfhost_last_validation", json.dumps(result))
    # Default the tool-user to whoever configured self-host (single-tenant
    # bench); operators can override it on Jarvis Settings. The jarvis__*
    # tools run under this user's Frappe permissions.
    if not (getattr(s, "selfhost_tool_user", "") or "").strip():
        u = frappe.session.user
        if u and u not in ("Guest", "Administrator"):
            s.db_set("selfhost_tool_user", u)
    frappe.db.commit()
    return {"ok": True, "result": result}


@frappe.whitelist()
def switch_to_managed() -> dict:
    """Switch back to Managed mode. Re-syncs the managed connection from admin
    if the bench was onboarded; otherwise just flips the flag.

    System Manager only."""
    frappe.only_for("System Manager")
    s = frappe.get_single("Jarvis Settings")
    s.db_set("deployment_mode", "Managed")
    frappe.db.commit()
    synced = None
    try:
        from jarvis import onboarding
        synced = onboarding.sync_connection()
    except Exception as e:
        synced = {"synced": False, "detail": str(e)}
    return {"ok": True, "deployment_mode": "Managed", "synced": synced}


@frappe.whitelist()
def get_status() -> dict:
    """Deployment status for the account/settings UI. System Manager only."""
    frappe.only_for("System Manager")
    s = frappe.get_single("Jarvis Settings")
    return {
        "deployment_mode": s.deployment_mode or "Managed",
        "agent_url": (s.agent_url or "") if (s.deployment_mode == "Self-Hosted") else "",
        "validated_at": str(s.selfhost_last_validated_at or ""),
        "stream": (s.selfhost_stream is None) or bool(s.selfhost_stream),
    }


def is_self_hosted() -> bool:
    """True iff this bench is configured for a self-hosted openclaw."""
    return (frappe.db.get_single_value("Jarvis Settings", "deployment_mode")
            or "Managed") == "Self-Hosted"


# --- active-turn marker (tool-card attribution for self-host) -------------
# openclaw's HTTP transport executes tools internally and returns only the
# final answer, and the plugin's call_tool callback carries only the openclaw
# session key - not our conversation. To still show tool cards in self-host
# chat, the worker records the in-flight turn here (keyed by the tool user),
# and call_tool reads it to attribute each tool call to that conversation.
# A self-hosted bench runs ~one turn at a time per tool user.
_ACTIVE_TURN_KEY = "jarvis:selfhost_active_turn:"


def set_active_turn(tool_user: str, *, conversation: str, owner: str, run_id: str) -> None:
    if not tool_user:
        return
    frappe.cache().set_value(
        _ACTIVE_TURN_KEY + tool_user,
        {"conversation": conversation, "owner": owner, "run_id": run_id},
        expires_in_sec=300,
    )


def get_active_turn(tool_user: str) -> dict | None:
    if not tool_user:
        return None
    return frappe.cache().get_value(_ACTIVE_TURN_KEY + tool_user) or None


def clear_active_turn(tool_user: str) -> None:
    if tool_user:
        frappe.cache().delete_value(_ACTIVE_TURN_KEY + tool_user)
