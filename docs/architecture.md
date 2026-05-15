# Architecture

## Product vision

Jarvis is structured as four layers, each building on the previous. Only Layer 1 is implemented today.

| Layer | What it does | Status |
|---|---|---|
| 1. Read & Understand | Permission-aware Q&A over ERPNext data. Tables, charts, saved views. | Foundation implemented (Phase 1 + Phase 2.1) |
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
