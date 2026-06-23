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

import contextlib
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
                     stream: int | str = 1, tool_user: str = "") -> dict:
    """Validate, then switch this bench to Self-Hosted mode pointed at the
    given openclaw. Refuses to persist if validation fails (no half-config).

    ``stream`` controls token-by-token SSE rendering of the agent's reply
    (default on; off => one-shot, for openclaw behind a buffering proxy).

    ``tool_user`` is the Frappe user the jarvis__* (ERP) tools run under. When
    omitted we keep any already-configured value, else default to the
    configuring user - but never Administrator/Guest, since running ERP tools
    as Administrator bypasses all DocType permissions. If it ends up unset
    (e.g. self-host configured while logged in as Administrator) we still save
    the connection but return a ``warning`` so the operator knows tool calls
    will be rejected until they pick a tool user.

    System Manager only."""
    frappe.only_for("System Manager")
    # Validate the tool user (cheap, synchronous) BEFORE the network/LLM
    # validate_connection so a typo'd user doesn't cost a full (deep) round-trip.
    # Reject Administrator (bypasses all DocType perms) and Guest, plus a missing
    # or disabled user - get_value("enabled") is None/0 for both.
    tu = (tool_user or "").strip()
    if tu and (tu in ("Guest", "Administrator")
               or not frappe.db.get_value("User", tu, "enabled")):
        return {"ok": False, "error": "invalid_tool_user",
                "detail": f"{tu!r} is not a valid, enabled, non-admin Frappe user"}

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
    # Tool user the jarvis__* tools run under: explicit choice > existing >
    # the configuring user (never Administrator/Guest - see docstring).
    if tu:
        s.db_set("selfhost_tool_user", tu)
    elif not (getattr(s, "selfhost_tool_user", "") or "").strip():
        u = frappe.session.user
        if u and u not in ("Guest", "Administrator"):
            s.db_set("selfhost_tool_user", u)
    frappe.db.commit()

    out = {"ok": True, "result": result}
    if not (getattr(s, "selfhost_tool_user", "") or "").strip():
        out["warning"] = (
            "Connection saved, but no Self-Host Tool User is set, so ERP tool "
            "calls will be rejected. Set 'Self-Host Tool User' in Jarvis "
            "Settings to a non-admin Frappe user."
        )
    return out


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
# chat, the worker records the in-flight turn here, and call_tool reads it to
# attribute each tool call back to that conversation.
#
# A self-hosted bench is single-tenant and normally runs one turn at a time
# per tool user, but two turns CAN overlap (the same user in two tabs, or two
# Frappe users sharing the bench). The callback cannot tell which turn a tool
# call belongs to, so instead of a single last-writer-wins slot - which would
# mis-file, and realtime-leak, one conversation's tool result into another -
# we track every in-flight turn and only attribute when exactly one is active;
# otherwise get_active_turn returns None and the tool card is dropped (fail
# safe, no cross-conversation leak). A crashed worker that never clears its
# marker self-heals: each per-run record carries a TTL, and stale run ids are
# pruned from the set on read.
_ACTIVE_TURN_KEY = "jarvis:selfhost_active_turn:"   # per-run turn data, keyed by run_id
_ACTIVE_RUNS_KEY = "jarvis:selfhost_active_runs:"   # in-flight run ids, keyed by tool_user
# Must outlive the longest possible turn so a marker never expires mid-flight.
# The RQ run_agent_turn budget is _AGENT_TURN_WORKER_TIMEOUT = 720s (jarvis/
# chat/api.py); a slow *streaming* reply keeps the HTTP turn open that long
# (openclaw_http_client._CHAT_TIMEOUT is inter-chunk, not total). If the record
# expired mid-turn, get_active_turn would treat a still-live run as dead, drop
# its tool card, and prune it - which could then make a genuinely concurrent
# turn look unambiguous and mis-attribute. 900s leaves margin over the budget.
_ACTIVE_TURN_TTL = 900


def _turn_key(run_id: str) -> str:
    return _ACTIVE_TURN_KEY + run_id


def set_active_turn(tool_user: str, *, conversation: str, owner: str, run_id: str) -> None:
    if not tool_user or not run_id:
        return
    # Best-effort + cosmetic (drives tool cards); never fail the turn on a
    # cache blip - mirrors the old set_value(suppress ConnectionError).
    with contextlib.suppress(Exception):
        frappe.cache().set_value(
            _turn_key(run_id),
            {"conversation": conversation, "owner": owner,
             "run_id": run_id, "tool_user": tool_user},
            expires_in_sec=_ACTIVE_TURN_TTL,
        )
        # Record MUST be written before the set membership: get_active_turn
        # treats a member whose record is missing as dead, so a run id must
        # never become visible in the set before its record exists.
        frappe.cache().sadd(_ACTIVE_RUNS_KEY + tool_user, run_id)


def get_active_turn(tool_user: str) -> dict | None:
    """The single in-flight turn for ``tool_user``, or None if there isn't an
    unambiguous one.

    Returns None when zero or 2+ turns are concurrently active, so a tool call
    is never attributed to - nor its result published into - the wrong
    conversation. Run ids whose per-run record has expired (e.g. a worker
    killed before clear_active_turn ran) are pruned from the set on read.
    """
    if not tool_user:
        return None
    runs_key = _ACTIVE_RUNS_KEY + tool_user
    try:
        members = {
            m.decode() if isinstance(m, bytes) else m
            for m in (frappe.cache().smembers(runs_key) or set())
        }
        if not members:
            return None
        live: list[dict] = []
        dead: list[str] = []
        for rid in members:
            data = frappe.cache().get_value(_turn_key(rid), use_local_cache=False)
            if data:
                live.append(data)
            else:
                dead.append(rid)
        if dead:
            frappe.cache().srem(runs_key, *dead)
        return live[0] if len(live) == 1 else None
    except Exception:
        return None


def clear_active_turn(tool_user: str, run_id: str = "") -> None:
    """Drop a finished turn. Pass ``run_id`` to clear just that turn (so an
    ending turn never wipes a concurrent one's marker); omit it to clear all of
    the tool user's turns (defensive cleanup)."""
    if not tool_user:
        return
    runs_key = _ACTIVE_RUNS_KEY + tool_user
    with contextlib.suppress(Exception):
        if run_id:
            frappe.cache().srem(runs_key, run_id)
            frappe.cache().delete_value(_turn_key(run_id))
            return
        for m in (frappe.cache().smembers(runs_key) or set()):
            rid = m.decode() if isinstance(m, bytes) else m
            frappe.cache().delete_value(_turn_key(rid))
        frappe.cache().delete_value(runs_key)
