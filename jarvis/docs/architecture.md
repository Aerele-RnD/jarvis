# Architecture

## Product vision

Jarvis is structured as four layers, each building on the previous. Only Layer 1 is implemented today.

| Layer | What it does | Status |
|---|---|---|
| 1. Read & Understand | Permission-aware Q&A over ERPNext data. Tables, charts, saved views. | Agent loop + chat UI live (Phase 1 + 2.1 + 2.2.a + 2.2.b). |
| 2. Proactive | Scheduled alerts, anomaly detection, digests pushed to the user | Future |
| 3. Reasoning | Forecasts, what-ifs, recommendations | Future |
| 4. Action | Agent writes back into ERPNext (drafts POs, posts entries) behind approvals | Future |

This document covers Layer 1 — everything currently in the repo.

## Component map (production target)

```
                ┌─────────────────────────────────┐
                │  Customer's Frappe Cloud bench  │
                │                                 │
                │   ┌─────────────────────────┐   │
                │   │ jarvis app (this repo)  │   │
                │   │  - Jarvis Settings      │   │
                │   │  - 5 data tools         │   │
                │   │  - call_tool HTTP API   │   │
                │   │  - chat UI + worker     │   │
                │   │  - on_update hook       │   │
                │   └─────────┬───────────────┘   │
                └─────────────│───────────────────┘
                              │ HTTPS (save → push creds)
                              ▼
                ┌─────────────────────────────────┐
                │  Aerele's infrastructure        │
                │                                 │
                │   ┌─────────────────────────┐   │
                │   │ jarvis_admin app        │   │
                │   │  (future; not built)    │   │
                │   │  - signup, payment      │   │
                │   │  - orchestration        │   │
                │   └─────────┬───────────────┘   │
                │             │ writes secret     │
                │             │ files, secrets.   │
                │             │ reload RPC        │
                │             ▼                   │
                │   ┌─────────────────────────┐   │
                │   │ openclaw container      │   │
                │   │  per-tenant gateway     │   │
                │   │  port 18789             │   │
                │   └─────────────────────────┘   │
                └─────────────────────────────────┘
```

## Component map (dev shape — what runs today)

For development we collapse `jarvis_admin` into the `jarvis` app itself, and openclaw runs locally via Docker. Everything is on one machine.

```
        localhost
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   ┌─────────────────────────────────────────────────────┐    │
│   │  jarvis.localhost (Frappe site)                     │    │
│   │                                                     │    │
│   │  ┌─────────────────────────────────────────────┐    │    │
│   │  │ jarvis app                                  │    │    │
│   │  │  - Jarvis Settings (LLM creds + operator)   │    │    │
│   │  │  - tools (get_schema, get_doc, ...)         │    │    │
│   │  │  - api.call_tool                            │    │    │
│   │  │  - on_update hook                           │    │    │
│   │  │  - openclaw_push (key write + secrets.reload│    │    │
│   │  │                   + docker restart)         │    │    │
│   │  │  - openclaw_bootstrap (start/stop/...)      │    │    │
│   │  └────────────────┬────────────────────────────┘    │    │
│   └───────────────────│─────────────────────────────────┘    │
│                       │                                      │
│                       │ writes secret file,                  │
│                       │ ws://127.0.0.1:18789 secrets.reload, │
│                       │ docker compose restart               │
│                       ▼                                      │
│   ┌─────────────────────────────────────────────────────┐    │
│   │  openclaw container (Docker)                        │    │
│   │  - Gateway on port 18789                            │    │
│   │  - openclaw.json mounted from openclaw_state/       │    │
│   │  - SecretRef "llm_key" -> /home/node/.openclaw/llm.key │ │
│   │  - HTTP /v1/chat/completions (OpenAI-compatible)    │    │
│   └─────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

The wire shape between the jarvis app and "the thing that controls openclaw" is identical in dev and production — only the deployment topology differs. When `jarvis_admin` is built, the `on_update` hook switches from calling local helpers to making an outbound HTTPS request; everything else stays the same.

## Data flow — saving Jarvis Settings

```
1. User edits LLM Provider / Model / API Key in Jarvis Settings → Save
2. Frappe runs validate(), which captures whether llm_api_key changed
   (must be done before Frappe's Password masking obscures the new value)
3. Frappe runs on_update()
4. on_update classifies the change:
     None → no LLM field changed → return early
     "reload" → only llm_api_key changed
     "restart" → llm_provider, llm_model, or llm_base_url changed
5. Guard: if Operator-tab fields aren't populated yet (gateway URL, token,
   key path, etc.) → record "skipped: operator config incomplete" and return
6. Dispatch:
     "reload"  → openclaw_push.push_creds_reload(self):
                 - write_key_file: atomic 0600 write of llm.key
                 - reload_secrets: WS connect handshake + secrets.reload RPC
     "restart" → openclaw_push.push_creds_restart(self, gateway_token):
                 - render_config: re-render openclaw.json from current Settings
                 - write to openclaw_config_path
                 - write_key_file: atomic 0600 write of llm.key
                 - restart_gateway: docker compose restart + poll /healthz
7. Record last_sync_at + last_sync_status via db_set (bypasses on_update
   to avoid recursion)
8. Failures DO NOT block the save — the new field values still persist
   and the failure is recorded as "failed: <ErrorType>: <message>"
```

## Identity propagation — Jarvis tools as registered openclaw plugin tools (Path A)

When openclaw's agent fires a `jarvis__*` tool call, the Frappe tool dispatcher
needs to know which Frappe user the call is running on behalf of so it can apply
that user's permissions via `frappe.set_user`.

**Background — two openclaw code paths.** openclaw exposes two ways for a
plugin to provide tools to the agent:

| Path | Hook ctx | Factory ctx | Used by |
|---|---|---|---|
| **Factory (registered plugin tool)** | full `PluginHookToolContext` with sessionKey, requesterSenderId, agentId, channelId | full `OpenClawPluginToolContext` | telegram, slack, discord, whatsapp, openclaw's own message/memory tools |
| **MCP server** (external server in `mcp.servers.*`) | only `{toolName, params, toolCallId}` — no session context | n/a | external MCP servers |

Jarvis initially shipped on the MCP path. It hit hard walls — the MCP-routed
before_tool_call invocation in openclaw passes no session context to plugin
hooks, and several alternative session-discovery mechanisms are gated to bundled
plugins. We pivoted to the **factory path**, the same path the chat channels
use. See [`decisions/2026-05-17-identity-propagation.md`](decisions/2026-05-17-identity-propagation.md)
for the full investigation — the four MCP+hook variants we tried, why each
was structurally blocked, and the trade-offs we accepted by moving to the
factory path.

**The Path A mechanism (Phase 2.2.a, refined 2026-05-18 → "Path A v2")** works as follows:

```
  1. chat.api._ensure_session_key (or demo.ask_one) calls openclaw
     sessions.create → receives sessionKey (e.g. "agent:abc123:main")

  2. Frappe inserts a "Jarvis Chat Session" row:
       session_key = <sessionKey>
       user        = <current Frappe user>
     and commits, making the mapping visible to subsequent HTTP requests.

  3. Openclaw runs the agent loop. The jarvis-openclaw-plugin has registered
     FIVE tools (jarvis__get_schema, jarvis__get_doc, jarvis__get_list,
     jarvis__run_report, jarvis__run_query) via the factory mechanism. When the
     agent invokes one, openclaw passes an OpenClawPluginToolContext with
     ctx.sessionKey to the tool factory.

  4. The tool's execute function POSTs the invocation to Frappe:
       POST /api/method/jarvis.api.call_tool
       X-Jarvis-Token:   <gateway_token>      ← proves request originated
                                                 inside the openclaw container
       X-Jarvis-Session: <sessionKey>          ← identity carrier
       X-Frappe-Site-Name: jarvis.localhost
       {"tool": "get_list", "args": {...}}

  5. jarvis.api.call_tool validates the token, looks up Jarvis Chat Session
     to map sessionKey → user, runs frappe.set_user(user), dispatches the
     tool through the Phase 1 tool registry, then restores the original
     session user.

  6. The tool's response is returned through openclaw to the LLM as the tool
     result. call_tool also persists a tool-role Jarvis Chat Message and
     publishes a realtime tool:result event so the chat UI sees the trace.
```

The env vars `JARVIS_FRAPPE_URL`, `JARVIS_GATEWAY_TOKEN`, and `JARVIS_SITE_NAME`
are baked into the container's env by `openclaw_bootstrap._write_env_file` so
the plugin can make the callbacks without any additional configuration.

**Path A v2 vs the original Path A (pre-2026-05-18):** the original design had the
plugin make a *separate* round-trip to `jarvis.api.lookup_user_by_session`
before each tool call, then forward both `X-Jarvis-User` and `X-Jarvis-Session`
headers. That round-trip was redundant — Frappe already owns the session→user
mapping. v2 drops the lookup endpoint and the `X-Jarvis-User` header
entirely; the plugin sends only the session, Frappe resolves identity itself.
Half the network calls per tool invocation, ~100 lines of code removed, no
client-side cache to keep coherent.

**What this replaces:** the MCP server at `jarvis.mcp.serve` and the
`before_tool_call` hook that injected `_user` into MCP params. Both are gone.
The Phase 1 surface (`jarvis.api.call_tool`) is now the single Frappe-side
tool entry point for both external Phase 1 callers and the openclaw plugin.

**Why the chat channels (Telegram/Slack/Discord/WhatsApp) "just work":** they
already live on the factory path, where openclaw's plugin SDK was designed to
flow session context to tool factories. Path A puts Jarvis on the same path.

## Chat UI (Phase 2.2.b)

The `/app/jarvis-chat` Desk page is a thin client over the Path A agent loop.
Three Frappe-side pieces:

1. **`jarvis.chat.api`** — whitelisted endpoints for `list_conversations`,
   `get_conversation`, `create_conversation`, `send_message`, and
   `archive_conversation`. `send_message` validates via
   `policy.validate_can_send` (stub), persists the user message, ensures the
   conversation has an openclaw `session_key` (creating one on first turn),
   and enqueues `jarvis.chat.worker.run_agent_turn` via `frappe.enqueue`.
   Returns `{ok, run_id, message_id}` in ~10ms.

2. **`jarvis.chat.worker.run_agent_turn`** — RQ job that holds the Python
   WebSocket to openclaw for the duration of the turn (typically 10-30s).
   Streams events through `OpenclawSession.stream_agent_turn`, persists
   deltas to `Jarvis Chat Message` (overwriting the cumulative `content` for
   the active assistant turn), and republishes each event via
   `frappe.publish_realtime("jarvis:event", payload, user=...)`.

3. **`jarvis.chat.stale_scan`** — scheduler job (every 5 minutes) that marks
   abandoned streaming messages errored. Recovers cleanly if a worker is
   killed mid-stream.

The browser subscribes to `frappe.realtime.on("jarvis:event", ...)` once and
routes events by `kind` (`assistant:delta`, `tool:start`, `tool:end`,
`tool:result`, `run:end`, `run:error`). Per-token latency from openclaw →
browser is ~10ms.

Tool args + results reach the chat UI directly through `call_tool` itself:
because the plugin sends `X-Jarvis-Session`, `call_tool` knows which
conversation the call belongs to and (a) persists a tool-role `Jarvis Chat
Message`, (b) publishes a `tool:result` realtime event. The browser groups
consecutive tool messages within a turn into a collapsable "Agent loop"
trace block.

The agent itself is seeded with a persona via `openclaw_workspace_seeds/`
(`IDENTITY.md`, `SOUL.md`, `AGENTS.md`, `USER.md`). `openclaw_bootstrap`
copies these into the openclaw workspace and sets
`agents.defaults.skipBootstrap: true` so the "who am I?" first-run ritual
never fires.

## Trust boundaries

- **Per-user permission inheritance.** Every tool calls `frappe.has_permission(...)` with the calling user. The agent never sees DocTypes or records the user can't see. A salesperson asking about Purchase Invoices gets `PermissionDeniedError`, not data leakage.
- **LLM key stays on disk, never in transit in plaintext beyond the bench host.** The key is written to `openclaw_state/llm.key` (mounted into the container as a SecretRef'd file). The `on_update` push is intra-host in dev. In production it'll be a cross-host HTTPS POST to the Aerele admin, which then writes the file on Aerele's infrastructure — but in either case the key stays on systems Aerele (or the customer) operates.
- **Openclaw gateway token authenticates writes.** All `secrets.reload` RPC calls and HTTP API calls present the gateway token (auto-generated at bootstrap, stored encrypted in Frappe Password field).
- **Save in Jarvis Settings never fails because openclaw is unreachable.** The on_update push runs after the save commits; failures are recorded but don't roll back the customer's edit. They retry later (re-save) or fix openclaw.

## What's not in this version

- Write/update/delete tools (current tools are all read-only)
- Signup, payment, billing, customer DB
- Real cross-host wire (dev does everything on localhost)
- `jarvis_admin` / `jarvis_fleet` orchestrator that runs openclaw per-tenant
- Private `jarvis-persona` repo + RO bind mount for shipped persona/skills
- Multi-tenant openclaw fleet management
- Tables / charts / saved-views rendering for tool output (markdown today)

See the workspace-only design docs (`docs/superpowers/specs/`) for the broader product spec; this README + the rest of `app/docs/` cover only what's actually shipped.
