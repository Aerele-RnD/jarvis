# Jarvis

AI superpowers for Frappe/ERPNext, powered by [openclaw](https://github.com/openclaw/openclaw).

Jarvis lets ERPNext users — especially business owners and execs — ask plain-English questions over their ERP data and get correct, permission-aware answers grounded in the actual records. It pairs an in-bench Frappe app (settings, permission-aware tool layer, HTTP API, on-save credentials propagation) with an openclaw agent runtime hosted per-tenant on Aerele's infrastructure. Data stays on the customer's bench; the agent brain lives in openclaw; permissions inherit from Frappe's own per-user checks.

**Status:** The end-to-end agent loop + chat UI are live, and the **Phase 3 SaaS control plane is built**: `jarvis_admin` (signup, Razorpay billing, fleet orchestration), the per-host `jarvis-fleet-agent` + Traefik TLS edge, `jarvis-openclaw-plugin` (the agent calling back into Frappe), and a RO-mounted `jarvis-persona`. **11 tools** (5 read + 6 write), identity via a single `X-Jarvis-Session` header (Path A v2). Customers connect via **Jarvis Cloud** ([docs/getting-started.md](jarvis/docs/getting-started.md)); a single-bench dev path also exists ([docs/local-dev.md](jarvis/docs/local-dev.md)). Production bring-up is documented + operator-run (see the `jarvis_admin` app's `docs/production-deploy.md`).

## Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/Aerele-RnD/jarvis --branch main
bench install-app jarvis
```

## Quick start (Jarvis Cloud — production)

```bash
# 1. Install the app on your site
bench --site <your-site> install-app jarvis
```
Then open **`/app/jarvis-onboarding`** in Desk → sign up + pay → the control
plane assigns you a managed openclaw container and stores its connection in
Jarvis Settings. Set your LLM provider/model/key in **Jarvis Settings**, then
chat at **`/app/jarvis-chat`**. Full walkthrough: [docs/getting-started.md](jarvis/docs/getting-started.md).

**Local single-bench dev** (run openclaw yourself, no control plane) →
[docs/local-dev.md](jarvis/docs/local-dev.md).

## Architecture at a glance

In production the customer site never runs openclaw — saving Jarvis Settings
POSTs to Aerele's control plane, which provisions/updates the container on the
fleet; the agent calls back into Frappe (`call_tool`) with per-user identity.
See [docs/architecture.md](jarvis/docs/architecture.md) for the full picture
(production vs dev shapes, identity flow, trust boundaries).

## Documentation

Start at **[`jarvis/docs/README.md`](jarvis/docs/README.md)** (docs index).

| Document | What it covers |
|---|---|
| [`docs/getting-started.md`](jarvis/docs/getting-started.md) | Production quick start: install → onboard → pay → chat |
| [`docs/architecture.md`](jarvis/docs/architecture.md) | Components (app + admin + fleet + plugin + persona), dev vs prod shapes, identity flow, trust boundaries |
| [`docs/configuration.md`](jarvis/docs/configuration.md) | Every Jarvis Settings field — customer-set vs admin-populated |
| [`docs/tools-api.md`](jarvis/docs/tools-api.md) | The 11 tools, the registry/dispatcher, the `call_tool` HTTP API + its two auth modes |
| [`docs/local-dev.md`](jarvis/docs/local-dev.md) | Single-bench dev: `openclaw_bootstrap`, local creds push, troubleshooting, chat ops |
| [`docs/development.md`](jarvis/docs/development.md) | Dev setup, running tests, project structure, recipes for adding tools/providers |
| [`docs/decisions/`](jarvis/docs/decisions/) | Architecture decision records. See [identity propagation](jarvis/docs/decisions/2026-05-17-identity-propagation.md) for why Path A (registered plugin tools) replaced the original MCP+hook design. |

## Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/jarvis
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

See [`jarvis/docs/development.md`](jarvis/docs/development.md) for the full dev workflow, recipes, and project layout.

## License

MIT
