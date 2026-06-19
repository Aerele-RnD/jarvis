# Self-Hosted (BYO) openclaw connection — Design

Date: 2026-06-18
Status: approved (Approach A), v1 = connect + chat
App: `jarvis` (customer Frappe app)

## Goal

Let a customer point `jarvis` at **their own openclaw server** (local or any hosted) instead of an Aerele-managed container, with **pre-connect validation**. This is the open-source / self-hosting path: users bring their own openclaw + their own LLM; Aerele's persona/skills and managed hosting remain the paid value. Configurable at onboarding and switchable later.

## Decisions (locked)

- **LLM ownership: user-side.** The user configures the LLM on their own openclaw. Jarvis never pushes LLM creds in self-hosted mode; it only verifies the LLM is ready during validation.
- **v1 scope: connect + chat.** ERP tools (the `jarvis-openclaw-plugin`) are **out of scope** for v1 (they require the user's openclaw to run the plugin + call back into Frappe — a later increment).
- **Approach A:** explicit `deployment_mode` flag + a dedicated, validated self-host path that reuses existing chat plumbing where possible and gates the admin/fleet calls off.

## Key technical finding (de-risks the design)

The chat **WS** path uses device-paired Ed25519 auth because openclaw **strips `operator.write` from non-loopback token-only WS clients** (verified: a token-only WS connect returns `role=operator, scopes=[]`, and `sessions.create` → "missing scope: operator.write"). Device pairing today requires fleet-agent filesystem access — unavailable for self-host.

**However**, openclaw's docs + our probes confirm the **HTTP OpenAI-compatible surface** (`POST /v1/chat/completions`) "restores the normal full operator default scope for shared-secret bearer auth." So **self-host chat uses the HTTP endpoint with `Authorization: Bearer <gateway_token>` — full scope, no device pairing, works for local *and* remote openclaw.** (We already saw this endpoint return real chat replies in earlier probes.)

→ **Self-host v1 transport = HTTP `/v1/chat/completions`** (not the WS device-paired flow). Managed mode is unchanged (keeps WS + pairing).

## Data model (Jarvis Settings)

Add to `Jarvis Settings`:
- `deployment_mode` — Select: `Managed` (default) | `Self-Hosted`.
- Reuse `agent_url` to store the self-host openclaw **HTTP base URL** (e.g. `http://host.docker.internal:19060` or `https://openclaw.example.com`). (In managed mode this is the `ws(s)://` gateway; in self-host it's the `http(s)://` base. Resolution keys off `deployment_mode`.)
- Reuse `agent_token` for the gateway bearer token.
- `selfhost_last_validated_at`, `selfhost_last_validation` (JSON/text) — last validation result for the status UI.

## Components

1. **`jarvis/selfhost.py`** (new) — the self-host connection unit.
   - `validate_connection(base_url, token, *, deep=False) -> dict` — runs the pre-connect checks, returns a structured per-check result (never raises for a "failed check"; raises only on programmer error). Pure-ish (HTTP I/O only), unit-testable with mocked HTTP.
   - `@frappe.whitelist test_connection(base_url, token, deep=False)` — System-Manager-gated wrapper for the UI "Test connection" button.
   - `@frappe.whitelist save_self_hosted(base_url, token)` — validate (must pass core checks) → set `deployment_mode=Self-Hosted`, store `agent_url`/`agent_token`, stamp validation. Refuses to save if validation fails.
   - `@frappe.whitelist switch_to_managed()` / status helpers as needed.

2. **`jarvis/chat/openclaw_http_client.py`** (new) — minimal HTTP chat client for self-host.
   - `stream_agent_turn(base_url, token, message, *, model="openclaw") -> Iterator[parsed events]` — POSTs to `{base_url}/v1/chat/completions` (stream:true SSE; buffered fallback), yields the same parsed-event shape `worker.py` consumes (assistant deltas + a terminal `lifecycle.end`/`error`). Mirrors the public contract of `OpenclawSession.stream_agent_turn` so the worker can branch cleanly.

3. **`jarvis/chat/worker.py`** — branch on `deployment_mode`: managed → existing `OpenclawSession` (WS); self-hosted → `openclaw_http_client`. No session/device pairing in self-host.

4. **`jarvis/chat/api.py`** — `_ensure_session_key()` is a no-op (or returns a synthetic key) in self-host (HTTP chat is stateless per call / openclaw manages its own session by `model`).

5. **Admin/fleet gating** — `onboarding.sync_connection`, daily admin crons, `account.*` admin calls, and `oauth.*` LLM-push become no-ops/guarded when `deployment_mode == Self-Hosted` (self-host has no admin/fleet).

6. **UX** — Onboarding wizard gets a top-level fork: "Aerele-managed" vs "Self-hosted openclaw". Self-host branch collects base URL + token → "Test connection" (shows per-check results) → Save. Account/settings page gets a "Connection" section to view status, re-test, and switch modes.

## Validation checks (the "test connection")

All HTTP, token-only, no pairing. Each returns `{check, ok, detail}`:
1. **URL shape** — well-formed http(s) URL.
2. **Reachable** — `GET {base}/healthz` → 200 within timeout.
3. **Auth** — `GET {base}/v1/models` with Bearer → 200 (401/403 ⇒ bad token).
4. **LLM ready** — `/v1/models` returns ≥1 model (LLM/agent configured). (`deep=True` additionally POSTs a tiny `chat/completions` "ping" and confirms a non-empty reply — truest check, but slow/costs an LLM call, so opt-in.)
5. **Version (best-effort)** — capture openclaw version if exposed (WS hello-ok `server.version` or an HTTP header); informational, non-blocking.

Save requires checks 1–4 to pass; deep test is optional.

## Error handling

- Validation never half-saves: `save_self_hosted` validates first; on failure returns the per-check failures and changes nothing.
- Chat HTTP errors (timeout, 401, 5xx, stream drop) map to the existing assistant-message error rows via `worker.py`'s `OpenclawUnreachableError` handling (reuse `jarvis.exceptions`).
- Switching modes is atomic (`db_set` + commit); chat history (Frappe-side) is preserved across switches.

## Testing

- **Unit:** `selfhost.validate_connection` with mocked HTTP for each pass/fail path; `openclaw_http_client` event mapping (SSE chunk → parsed events → lifecycle.end).
- **Integration / acceptance (this session):** stand up a local plain openclaw (no persona/plugin) with a gateway token + an LLM; create a **new user** on `site.jarvis`; configure self-hosted mode pointed at it; run validation (all green); send a chat message and confirm a reply. "Everything works" = validated connection + a real chat turn against the local openclaw.

## Out of scope (v1)

- ERP tools / plugin in self-host (next increment: plugin install + gateway-token issuance + callback reachability checks).
- Jarvis-side LLM push to the user's openclaw (decided: user-side).
- WS device-pairing for self-host (HTTP transport avoids it).
- Self-hosting the admin/fleet plane.

## Risks

- HTTP `/v1/chat/completions` doesn't carry the WS event richness (tool events) — fine for v1 (no tools); assistant text + lifecycle is enough.
- openclaw HTTP surface/version drift — pin checks to documented endpoints (`/healthz`, `/v1/models`, `/v1/chat/completions`); validation surfaces incompatibility clearly.
