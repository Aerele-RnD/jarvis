# Jarvis

AI superpowers for Frappe/ERPNext, powered by [openclaw](https://github.com/openclaw/openclaw).

Jarvis lets ERPNext users — especially business owners and execs — ask plain-English questions over their ERP data and get correct, permission-aware answers grounded in the actual records. It pairs an in-bench Frappe app (settings, permission-aware tool layer, HTTP API, on-save credentials propagation) with an openclaw agent runtime hosted per-tenant on Aerele's infrastructure. Data stays on the customer's bench; the agent brain lives in openclaw; permissions inherit from Frappe's own per-user checks.

**Status:** End-to-end agent loop is live, with a chat UI in Desk. Phase 1 (foundation), Phase 2.1 (credentials update stack), Phase 2.2.a (Path A agent loop), and Phase 2.2.b (chat UI inside Desk) are implemented and verified against a real openclaw container. Open `/app/jarvis-chat` in your bench, ask "list 3 customers" and watch the agent stream a permission-aware reply. 183 Frappe-side + 20 plugin-side unit tests passing. Phase 3 (per-tenant SaaS control plane: `jarvis_admin` + `jarvis_fleet`) is next.

## Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/Aerele-RnD/jarvis --branch main
bench install-app jarvis
```

## Quick start

```bash
# 1. Install the app on your site
bench --site <your-site> install-app jarvis

# 2. Bring openclaw up locally (requires Docker Desktop running)
bench --site <your-site> execute jarvis.openclaw_bootstrap.start

# 3. Open Jarvis Settings in Desk
#    http://<your-site>:8000/app/jarvis-settings
#    Fill the Language Model section: provider, model, API key. Save.

# 4. Confirm the push worked: Operator tab -> Last Sync Status reads "ok (restart)"

# 5. Run an end-to-end agent turn (Path A) — agent invokes jarvis__get_list
#    under the named Frappe user's permissions and returns real customer rows:
bench --site <your-site> execute jarvis.demo.ask_one \
  --kwargs '{"user":"Administrator","message":"use the jarvis__get_list tool to list 3 customers, show me just the names"}'
```

## Architecture at a glance

```
┌──────────────────────────┐         ┌──────────────────────────────┐
│  Jarvis Settings (Desk)  │  save   │  jarvis.openclaw_push        │
│  - LLM provider/model    │ ──────► │  - write_key_file            │
│  - LLM API key           │         │  - reload_secrets   (WS RPC) │
└──────────────────────────┘         │  - restart_gateway  (docker) │
                                     └──────────────┬───────────────┘
                                                    ▼
                                     ┌──────────────────────────────┐
                                     │  openclaw container          │
                                     │  - LLM gateway, port 18789   │
                                     │  - SecretRef -> llm.key file │
                                     │  - HTTP /v1/chat/completions │
                                     └──────────────────────────────┘
```

End-to-end: a save in Jarvis Settings detects the change (key only vs provider/model/base_url), pushes the right update to openclaw (hot `secrets.reload` for key changes, full container restart for provider changes), and openclaw's next LLM call uses the new credentials.

## Documentation

| Document | What it covers |
|---|---|
| [`jarvis/docs/architecture.md`](jarvis/docs/architecture.md) | Product vision, component map, data flow, trust boundaries |
| [`jarvis/docs/configuration.md`](jarvis/docs/configuration.md) | Every Jarvis Settings field, what it does, how it gets populated |
| [`jarvis/docs/tools-api.md`](jarvis/docs/tools-api.md) | The four data tools, the registry/dispatcher, the whitelisted `call_tool` HTTP API |
| [`jarvis/docs/operations.md`](jarvis/docs/operations.md) | Bench commands (`openclaw_bootstrap.*`), credentials update flow, troubleshooting |
| [`jarvis/docs/development.md`](jarvis/docs/development.md) | Dev setup, running tests, project structure, recipes for adding tools/providers |
| [`jarvis/docs/decisions/`](jarvis/docs/decisions/) | Architectural decision records. See [identity propagation](jarvis/docs/decisions/2026-05-17-identity-propagation.md) for why Path A (registered plugin tools) replaced the original MCP+hook design. |

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
