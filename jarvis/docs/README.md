# Jarvis docs

Jarvis gives Frappe/ERPNext users plain-English, permission-aware answers over
their own data, powered by an [openclaw](https://github.com/openclaw/openclaw)
agent. This `jarvis` app runs on the customer's Frappe site; the agent runtime
runs in an openclaw container that **Aerele's control plane provisions and
manages** (see "two ways to run", below).

## Two ways to run Jarvis

| Mode | Who manages the container | Start here |
|---|---|---|
| **Jarvis Cloud (production)** — default | Aerele's `jarvis_admin` control plane assigns each site a managed openclaw container on the fleet; the customer just signs up + pays. | [getting-started.md](getting-started.md) |
| **Local single-bench (development)** | You run openclaw yourself with `openclaw_bootstrap` on one bench. No admin, no billing, no TLS. | [local-dev.md](local-dev.md) |

Both share the same in-app surface (Jarvis Settings, the tools, `call_tool`, the
chat UI). They differ only in *who provisions openclaw* — in production the
customer app never runs Docker; on save it calls the admin over HTTPS.

## Map

| Document | What it covers |
|---|---|
| [getting-started.md](getting-started.md) | Production quick start: install → onboard → pay → chat |
| [architecture.md](architecture.md) | Components (app + admin + fleet + plugin + persona), dev vs prod shapes, identity flow, trust boundaries |
| [configuration.md](configuration.md) | Every Jarvis Settings field — what the customer sets vs what the admin populates |
| [tools-api.md](tools-api.md) | The 11 tools, the registry, the `call_tool` HTTP API + its two auth modes |
| [local-dev.md](local-dev.md) | Single-bench dev: `openclaw_bootstrap`, local creds push, troubleshooting, chat ops |
| [development.md](development.md) | Contributing: dev setup, tests, project structure, recipes |
| [decisions/](decisions/) | Architecture decision records (e.g. why Path A replaced MCP) |

**Operators** running the Jarvis Cloud platform (control plane + fleet) — see the
`jarvis_admin` app docs, starting at its `docs/production-deploy.md`.
