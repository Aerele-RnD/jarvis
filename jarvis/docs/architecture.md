# Architecture

## Product vision

Jarvis is structured as four layers, each building on the previous.

| Layer | What it does | Status |
|---|---|---|
| 1. Read & Understand | Permission-aware Q&A over ERPNext data. | Live (agent loop + chat UI). |
| 2. Proactive | Scheduled alerts, anomaly detection, digests | Future |
| 3. Reasoning | Forecasts, what-ifs, recommendations | Future |
| 4. Action | Agent writes back into ERPNext behind approvals | Layer-1 write tools exist (create/update/submit/cancel/delete/amend, confirm-first); workflows are future |

## Components

The full system spans several repos:

- **`jarvis`** (this repo) — the app installed on the **customer's** Frappe site:
  Jarvis Settings, the permission-aware tools + `call_tool` HTTP API, the chat
  UI + worker, and the `on_update` hook that propagates LLM credentials.
- **`jarvis_admin`** — Aerele's central **control plane** (Frappe app at
  `admin.jarvis.aerele.in`): signup, billing (Razorpay), and orchestration of a
  **fleet** of openclaw containers. *Built and live* (not "future").
- **`jarvis-fleet-agent`** — a per-host data-plane service the admin calls over
  HTTPS to provision/manage openclaw containers; **Traefik** terminates TLS for
  tenant subdomains.
- **`jarvis-openclaw-plugin`** — registered openclaw tools that call back into
  the customer's Frappe (`call_tool`) with per-user identity (Path A v2, below).
- **`jarvis-persona`** — persona/skills, RO-mounted into every container.

### Production shape (Jarvis Cloud)

The customer site **never runs Docker or openclaw**. The admin owns the
container lifecycle on the fleet.

```
  Customer Frappe site (jarvis app)
    - Jarvis Settings, tools, call_tool, chat UI
    - on_update hook
        │  save LLM creds → HTTPS POST (admin api token)
        ▼
  admin.jarvis.aerele.in  (jarvis_admin control plane)
    - signup / billing / fleet orchestration
        │  HTTPS (bearer) → fleet agent
        ▼
  Fleet host: jarvis-fleet-agent + Traefik
    - provisions the customer's openclaw container (persona + plugin mounted)
    - tenant reachable at wss://<slug>.jarvis.aerele.in (TLS via Traefik)
        │  openclaw agent runs a tool → jarvis-openclaw-plugin
        ▼
  back to the Customer Frappe site:  POST /api/method/jarvis.api.call_tool
```

On save, `Jarvis Settings.on_update` → **`_sync_via_admin`** (because
`jarvis_admin_url` is set) → `admin_client.post_update_llm_creds` → admin →
fleet agent applies the creds to the container.

### Local dev shape (single bench)

Everything on one machine; you run openclaw yourself via `openclaw_bootstrap`
(see [local-dev.md](local-dev.md)). On save, `on_update` →
**`_sync_via_local_openclaw`** (because `jarvis_admin_url` is blank) → the
`openclaw_push` helpers write the key file + `secrets.reload` over WS or
`docker compose restart`.

```
  localhost
    jarvis app  ──on_update (jarvis_admin_url unset)──►  openclaw_push
                                                          (write llm.key,
                                                           secrets.reload WS,
                                                           docker restart)
                                                              │
                                                              ▼
                                                   openclaw container (Docker)
                                                   gateway :18789
```

**Same wire shape, different topology.** The on_update hook picks the path by
whether `jarvis_admin_url` is set — that's the only branch. (Note: dev uses the
local path; production sets `jarvis_admin_url` to the admin URL.)

## Identity propagation — Path A v2

When openclaw's agent fires a `jarvis__*` tool, the Frappe dispatcher must run it
as the right Frappe user. Jarvis registers its tools via openclaw's **factory
path** (the same path the chat channels use), which carries `ctx.sessionKey`.
(It originally shipped on the MCP path, which passed no session context to plugin
hooks — see [decisions/2026-05-17-identity-propagation.md](decisions/2026-05-17-identity-propagation.md).)

```
  1. A chat turn calls openclaw sessions.create → sessionKey.
  2. Frappe inserts a "Jarvis Chat Session" row: session_key → user.
  3. The agent invokes a jarvis__* tool; the plugin's execute() POSTs:
       POST /api/method/jarvis.api.call_tool
       X-Jarvis-Token:   <gateway token>     (proves it came from the container)
       X-Jarvis-Session: <sessionKey>         (identity carrier)
       {"tool": "get_list", "args": {...}}
  4. call_tool validates the token, maps sessionKey → user via Jarvis Chat
     Session, runs frappe.set_user(user), dispatches the tool, restores the user.
```

The plugin reads `JARVIS_FRAPPE_URL`, `JARVIS_GATEWAY_TOKEN`, `JARVIS_SITE_NAME`
from its container env — injected by the fleet agent at assignment (prod) or by
`openclaw_bootstrap` (dev). `call_tool` is the single Frappe-side tool entry
point for both the plugin and any external API caller.

## Chat UI

`/app/jarvis-chat` is a thin client over the agent loop: `jarvis.chat.api`
(whitelisted endpoints; `send_message` enqueues a worker), `jarvis.chat.worker.
run_agent_turn` (holds the WS for the turn, streams deltas to `Jarvis Chat
Message`, republishes via `frappe.publish_realtime`), and `jarvis.chat.stale_scan`
(every-5-min cleanup of abandoned streams). The browser subscribes once to
`jarvis:event` and routes by `kind`. Tool args/results reach the UI through
`call_tool` itself (it persists a tool-role message + publishes `tool:result`).

The agent is seeded with persona files from `jarvis-persona` (prod, RO-mounted)
or `openclaw_workspace_seeds/` via `openclaw_bootstrap` (dev), with
`agents.defaults.skipBootstrap: true`.

## Trust boundaries

- **Per-user permission inheritance.** Every tool calls
  `frappe.has_permission(...)` as the calling user; the agent never sees what the
  user can't.
- **LLM key stays on systems the operator/customer runs.** Written to the
  container's `llm.key` (a SecretRef'd file). In prod the `on_update` push is a
  cross-host HTTPS POST to the admin, which routes it to the fleet agent.
- **Gateway token authenticates writes** (`secrets.reload`, the plugin's
  `X-Jarvis-Token`); stored encrypted in a Frappe Password field.
- **A Settings save never fails because openclaw is unreachable** — the push runs
  after commit; failures are recorded, not rolled back.

## What's not in this version
- Layers 2–4 (proactive / reasoning / approval workflows).
- Tables/charts/saved-view rendering for tool output (markdown today).
- HA / multi-region for the control plane (single control-plane host + N fleet
  hosts is the v1 shape).

The workspace-only design docs (`docs/superpowers/specs/`) hold the broader
product spec; this doc set covers what ships in the repos.
