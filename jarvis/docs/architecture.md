# Architecture

## Product vision

Jarvis is structured as four layers, each building on the previous. Only Layer 1 is implemented today.

| Layer | What it does | Status |
|---|---|---|
| 1. Read & Understand | Permission-aware Q&A over ERPNext data. Tables, charts, saved views. | Agent loop live (Phase 1 + 2.1 + 2.2.a). Chat UI in Desk (2.2.b) is next. |
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
                │   │  - 4 data tools         │   │
                │   │  - call_tool HTTP API   │   │
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
use. See `docs/superpowers/decisions/2026-05-17-identity-propagation.md` for the
full investigation and the four MCP+hook variants we tried before pivoting.

**The Path A mechanism (Phase 2.2.a)** works as follows:

```
  1. demo.ask_one (or future chat-UI path) calls openclaw sessions.create
     → receives sessionKey (e.g. "agent:abc123:main")

  2. demo.ask_one immediately inserts a "Jarvis Chat Session" row:
       session_key = <sessionKey>
       user        = "Administrator"   ← the initiating Frappe user
     and calls frappe.db.commit() so the row is visible to subsequent HTTP
     requests.

  3. openclaw runs the agent loop. The jarvis-openclaw-plugin has registered
     four tools (jarvis__get_schema, jarvis__get_doc, jarvis__get_list,
     jarvis__run_report) via the factory mechanism. When the agent invokes one,
     openclaw passes a OpenClawPluginToolContext containing ctx.sessionKey
     to the tool factory.

  4. The tool's execute function:
     a. Reads ctx.sessionKey.
     b. Checks an in-memory cache (Map<sessionKey, user>). On a cache miss it
        POSTs to:
          POST /api/method/jarvis.api.lookup_user_by_session
          X-Jarvis-Token: <gateway_token>
          X-Frappe-Site-Name: jarvis.localhost
          {"session_key": "<sessionKey>"}
        Frappe reads "Jarvis Chat Session" and returns {"user": "Administrator"}.
     c. POSTs the actual tool invocation to Frappe:
          POST /api/method/jarvis.api.call_tool
          X-Jarvis-Token: <gateway_token>
          X-Jarvis-User: Administrator
          X-Frappe-Site-Name: jarvis.localhost
          {"tool": "get_list", "args": {...}}

  5. jarvis.api.call_tool reads the X-Jarvis-User header, calls
     frappe.set_user(user), dispatches the tool through the existing Phase 1
     tool registry, then restores the original session user.

  6. The tool's response is returned through openclaw to the LLM as the tool
     result.
```

The env vars `JARVIS_FRAPPE_URL`, `JARVIS_GATEWAY_TOKEN`, and `JARVIS_SITE_NAME`
are baked into the container's env by `openclaw_bootstrap._write_env_file` so
the plugin can make the callbacks without any additional configuration.

**What this replaces:** the MCP server at `jarvis.mcp.serve` and the
`before_tool_call` hook that injected `_user` into MCP params. Both are gone.
The Phase 1 surface (`jarvis.api.call_tool`) is now the single Frappe-side
tool entry point for both external Phase 1 callers and the openclaw plugin.

**Why the chat channels (Telegram/Slack/Discord/WhatsApp) "just work":** they
already live on the factory path, where openclaw's plugin SDK was designed to
flow session context to tool factories. Path A puts Jarvis on the same path.

## Trust boundaries

- **Per-user permission inheritance.** Every tool calls `frappe.has_permission(...)` with the calling user. The agent never sees DocTypes or records the user can't see. A salesperson asking about Purchase Invoices gets `PermissionDeniedError`, not data leakage.
- **LLM key stays on disk, never in transit in plaintext beyond the bench host.** The key is written to `openclaw_state/llm.key` (mounted into the container as a SecretRef'd file). The `on_update` push is intra-host in dev. In production it'll be a cross-host HTTPS POST to the Aerele admin, which then writes the file on Aerele's infrastructure — but in either case the key stays on systems Aerele (or the customer) operates.
- **Openclaw gateway token authenticates writes.** All `secrets.reload` RPC calls and HTTP API calls present the gateway token (auto-generated at bootstrap, stored encrypted in Frappe Password field).
- **Save in Jarvis Settings never fails because openclaw is unreachable.** The on_update push runs after the save commits; failures are recorded but don't roll back the customer's edit. They retry later (re-save) or fix openclaw.

## What's not in this version

- Chat UI inside Desk
- Real agent loop / streaming LLM responses to a user
- Signup, payment, billing, customer DB
- Real cross-host wire (dev does everything on localhost)
- Real `jarvis_admin` orchestrator that runs openclaw per-tenant
- Multi-tenant openclaw fleet management
- Tables / charts / saved-views rendering for tool output

See the workspace-only design docs (`docs/superpowers/specs/`) for the broader product spec; this README + the rest of `app/docs/` cover only what's actually shipped.
