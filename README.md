# Jarvis

AI superpowers for Frappe/ERPNext, powered by [openclaw](https://github.com/openclaw/openclaw).

Jarvis lets ERPNext users — especially business owners and execs — ask plain-English questions over their ERP data and get correct, permission-aware answers grounded in the actual records. It pairs an in-bench Frappe app (settings, MCP-style tool layer, HTTP API, on-save credentials propagation) with an openclaw agent runtime hosted per-tenant on Aerele's infrastructure. Data stays on the customer's bench; the agent brain lives in openclaw; permissions inherit from Frappe's own per-user checks.

**Status:** Phase 1 (foundation: settings, four permission-aware tools, HTTP API) and Phase 2.1 (credentials update stack: Operator tab + openclaw bootstrap + on_update hook → openclaw secrets.reload / restart) are implemented and end-to-end verified against a real openclaw container. 90 unit tests passing. Phase 2.2 (chat UI + agent loop end-to-end) is next.

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
#    Then make a real LLM call through openclaw:
curl http://127.0.0.1:18789/v1/chat/completions \
  -H "Authorization: Bearer $(grep -oP '"token":\s*"\K[^"]+' \
       /Users/$USER/bench/develop/jarvis/openclaw_state/openclaw.json)" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw/default","messages":[{"role":"user","content":"hi"}]}'
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
