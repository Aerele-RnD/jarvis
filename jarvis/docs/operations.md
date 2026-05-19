# Operations

How to run Jarvis day-to-day: bring openclaw up, configure credentials, watch the sync, troubleshoot when something doesn't work.

## Prerequisites

- **Docker Desktop** running (`docker info` succeeds)
- **Frappe bench** with this app installed: `bench --site <site> install-app jarvis`
- **MariaDB** and **Redis** running. Bench's `bench start` spins up Redis on ports 11000 (queue) and 13000 (cache); both are required for tests and for the on_update hook to work without hitting an unrelated Frappe sync-queue assertion.
- The site reachable: `curl -sI http://<site>:8000` returns 200

## Bench commands: `openclaw_bootstrap`

Provisioning and lifecycle for the local openclaw container. Invoked via:

```bash
bench --site <site> execute jarvis.openclaw_bootstrap.<function>
```

### `start`

```bash
bench --site jarvis.localhost execute jarvis.openclaw_bootstrap.start
```

What it does, in order:

1. Resolve workspace root (Frappe bench's parent dir).
2. Compute default paths for state files (`<workspace>/openclaw_state/openclaw.json`, `.../llm.key`, `.../.env`) and for the openclaw compose dir (`<workspace>/openclaw/`).
3. Populate `Jarvis Settings` operator-tab fields with those defaults via `db_set` if they're empty. Existing values are preserved.
4. Generate a gateway token via `secrets.token_urlsafe(32)` if `agent_token` is empty. Persist via `db_set`. Re-runs preserve the existing token.
5. Create `<workspace>/openclaw_state/` if missing.
6. Create a placeholder `llm.key` (mode 0600) if it doesn't exist. The file contains a non-empty placeholder string (`PLACEHOLDER-set-llm_api_key-in-Jarvis-Settings`) because openclaw's SecretRef resolver fails-fast on empty values and refuses to boot. The customer's first save of Jarvis Settings with a real LLM API key overwrites this via the `on_update` hook. **Existing keys are not overwritten** — once a real key has been written, re-running `start` preserves it.
7. Render `openclaw.json` from current Jarvis Settings values via `openclaw_config.render_config`. If Settings have no provider/model yet, the renderer uses `STUB_DEFAULTS` (Moonshot/`kimi-k2.6` against Moonshot's default base URL with the placeholder key file) so openclaw still boots — LLM calls will fail until creds are filled, but the rest of the pipeline (`secrets.reload`, restart) is exercisable.
8. Write `<workspace>/openclaw_state/.env` with `OPENCLAW_CONFIG_DIR`, `OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest`, `OPENCLAW_GATEWAY_PORT=18789`, `OPENCLAW_GATEWAY_BIND=lan`.
9. `docker compose pull openclaw-gateway` (separate from `up` so first-run image pulls are visible; 600s timeout).
10. `docker compose up -d openclaw-gateway` (60s timeout).
11. Poll `http://127.0.0.1:18789/healthz` until 200 or 60s timeout.
12. Record `last_sync_at` + `last_sync_status = "openclaw started"`.

**Idempotent.** Re-running `start` after the container is already up: paths/token preserved, `llm.key` untouched, `openclaw.json` re-rendered (will be identical if Settings haven't changed), `docker compose up -d` is a no-op when the container is healthy.

### `stop`

```bash
bench --site jarvis.localhost execute jarvis.openclaw_bootstrap.stop
```

Reads `agent_compose_dir` from Settings, runs `docker compose -f <dir>/docker-compose.yml down` with the `.env` file if it exists. Records `last_sync_status = "openclaw stopped"`. Raises `OpenclawRestartFailedError` if `docker compose down` fails.

### `status`

```bash
bench --site jarvis.localhost execute jarvis.openclaw_bootstrap.status
```

Prints (and returns) a dict:

```json
{
  "container": "running",
  "image": "ghcr.io/openclaw/openclaw:latest",
  "health": "healthy",
  "gateway_url": "http://127.0.0.1:18789"
}
```

`container` is `running` / `stopped` / `not_created`. `health` is `healthy` / `unhealthy` / `unknown`. Doesn't raise on failure — degrades to `not_created` / `unknown` if the inspect commands fail.

### `restart`

```bash
bench --site jarvis.localhost execute jarvis.openclaw_bootstrap.restart
```

Calls `stop()` then `start()`. Failure of `stop()` (e.g. container wasn't running) is swallowed and execution proceeds to `start()`. Re-renders `openclaw.json` from current Settings, so this is also the way to apply config changes that don't go through the on_update hook (e.g. you edited `openclaw.json` by hand and want to revert).

## Credentials update flow

When the customer saves Jarvis Settings, the `on_update` hook on the `JarvisSettings` controller decides what to push to openclaw.

```
1. validate() runs first. It captures whether `llm_api_key` changed against the
   pre-save snapshot (using flags), BEFORE Frappe's _save_passwords() masks the
   field to "*****" on `self`.

2. on_update() runs. It classifies the change:

     None       → no LLM-relevant field changed → return early (no-op).
     "reload"   → only llm_api_key changed.
     "restart"  → llm_provider, llm_model, or llm_base_url changed (with or
                  without an accompanying key change).

3. Guard: every action requires the Operator-tab fields to be populated.
     reload  needs: agent_url, agent_token, agent_llm_key_path
     restart needs: all of the above + agent_config_path + agent_compose_dir
   Missing any → record "skipped: operator config incomplete; run
   jarvis.openclaw_bootstrap.start first" and return.

4. Dispatch:
     "reload"  → jarvis.openclaw_push.push_creds_reload(self):
                  - write_key_file(<llm_key_path>, <new key>)  (atomic 0600)
                  - reload_secrets(<gateway_url>, <gateway_token>)
                      · open WebSocket
                      · send connect frame with role=operator, auth.token
                      · send {method: "secrets.reload"}
                      · await ack, close

     "restart" → jarvis.openclaw_push.push_creds_restart(self, <gateway_token>):
                  - render_config(self, gateway_token)  → new openclaw.json
                  - write to <config_path>
                  - write_key_file(<llm_key_path>, <new key>)
                  - restart_gateway(<compose_dir>)
                      · docker compose restart openclaw-gateway
                      · poll http://127.0.0.1:18789/healthz

5. Record outcome via db_set (bypasses on_update, no recursion):
     success → last_sync_at = now(), last_sync_status = "ok (reload)" or "ok (restart)"
     failure → last_sync_status = "failed: <ErrorType>: <message>",
               log to Frappe Error Log
               (the save itself still succeeds — new field values persist)
```

`llm_temperature` and `llm_max_output_tokens` changes are deliberately ignored by the classifier — they're not part of `openclaw.json`, they'll be passed as request-time params when the Phase 2.2 agent loop is wired up.

## Manual operations

### Read the gateway token

In the browser: open Jarvis Settings → Operator tab → click the eye icon next to "Gateway Token".

From shell:
```bash
cat /Users/<you>/bench/develop/jarvis/openclaw_state/openclaw.json \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['gateway']['auth']['token'])"
```

### Inspect the rendered openclaw config

```bash
cat /Users/<you>/bench/develop/jarvis/openclaw_state/openclaw.json | jq .
```

### Force a re-push

If `last_sync_status` reads `failed: ...` and you've fixed the underlying issue (e.g. brought openclaw back up), trigger a re-push by opening Jarvis Settings, making any LLM field change (even add and remove a trailing space in the API key), and saving. The hook will fire and record a new status.

Alternatively, for a clean re-render:
```bash
bench --site jarvis.localhost execute jarvis.openclaw_bootstrap.restart
```

### Make a real LLM call (smoke test the LLM pipeline)

```bash
TOKEN=$(python3 -c "import json; print(json.load(open('/Users/<you>/bench/develop/jarvis/openclaw_state/openclaw.json'))['gateway']['auth']['token'])")

curl http://127.0.0.1:18789/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model":"openclaw/default","messages":[{"role":"user","content":"hi"}]}'
```

Note: `"model": "openclaw/default"` selects the *agent* default, which in turn uses the provider/model configured in `agents.defaults.model.primary` (rendered from Jarvis Settings). Backend model overrides via `x-openclaw-model` header are available but not needed.

### Run a full agent turn (Path A v2 end-to-end)

`jarvis.demo.ask_one` opens an openclaw session as a named Frappe user, sends a chat message, waits for the agent loop to complete, and prints a structured trace. This is the canonical smoke test that the agent + plugin + identity propagation pipeline is healthy.

```bash
bench --site jarvis.localhost execute jarvis.demo.ask_one \
  --kwargs '{"user":"Administrator","message":"use the jarvis__get_list tool to list 3 customers, show me just the names"}'
```

Expected trace:
```
[session created] key=agent:main:dashboard:<uuid>
[chat session row created] sessionKey=... user='Administrator'
[run accepted] runId=...
[lifecycle] run started
[tool→start] jarvis__get_list({})
[tool→ok] jarvis__get_list status=completed
[lifecycle] run ended cleanly
```

The openclaw container log will show the agent rendering a reply that includes real customer names from the Frappe DB. If the demo's `tool_calls: []` stays empty, the most likely cause is a plugin load failure — check `docker compose logs openclaw-gateway | grep jarvis-openclaw-plugin`. The workspace doc `docs/superpowers/verification/2026-05-17-phase-2-2-a-path-a-agent-loop.md` has the full runbook.

## Troubleshooting

| Symptom | Likely cause | First thing to check |
|---|---|---|
| `bench execute jarvis.openclaw_bootstrap.start` hangs on docker compose pull | Slow network or unreachable registry | `docker pull ghcr.io/openclaw/openclaw:latest` directly; check connectivity |
| Container starts but `/healthz` never returns 200 | Openclaw rejected the rendered config | `docker compose -f openclaw/docker-compose.yml logs openclaw-gateway`; cross-check `cat openclaw_state/openclaw.json` against openclaw's schema |
| Curl to `/v1/chat/completions` returns 401 | Wrong gateway token in `Authorization`, OR HTTP API not enabled in config | Verify the token matches `openclaw.json`; verify `gateway.http.endpoints.chatCompletions.enabled: true` |
| Curl returns 404 on the endpoint | Wrong path or HTTP API disabled | The exact path is `/v1/chat/completions`; check the config flag |
| `last_sync_status = "failed: OpenclawReloadFailedError: timeout waiting for response"` | WS connect handshake didn't get a response within 10s | `docker compose logs openclaw-gateway` for protocol-version mismatches |
| `last_sync_status = "skipped: operator config incomplete"` | Operator-tab fields aren't populated | Run `bench execute jarvis.openclaw_bootstrap.start` to auto-populate |
| `last_sync_status = "failed: OpenclawUnreachableError: ..."` | Container not running or network blocked | `bench execute jarvis.openclaw_bootstrap.status`; if `container = stopped` then `start` again |
| Save in Jarvis Settings hangs for ~10s | Openclaw is unreachable; on_update is waiting on the WebSocket timeout | Acceptable but slow; openclaw being down should be rare in normal use |
| Tests fail with `Should not fail silently in tests` | Bench Redis isn't running on port 13000 | `bench start` (which spins up Redis via Procfile) |
| Tests fail with `ModuleNotFoundError: No module named 'jarvis'` | Bench worker started before app was installed (stale `sys.path`) | `pkill -f "bench serve"` then `bench start` fresh |
| `bench setup requirements` errors with `InvalidGitRepositoryError` for jarvis | App is symlinked to a non-git-root directory | The app source needs to be its own git repo (it is, after the Phase 1 restructure). Make sure `apps/jarvis/.git` exists. |

## Chat operations (Phase 2.2.b)

### Open the chat page

`http://<site>:8000/app/jarvis-chat` — accessible to any signed-in user. Each user sees only their own conversations.

### Restart chat workers

Workers are standard Frappe RQ workers. Inspect them:

```bash
cd ~/bench/develop/jarvis/bench
bench --site jarvis.localhost rq-list
```

Restart all (in dev `bench start` already runs them; in production: `supervisorctl restart all`).

### Inspect a stuck streaming message

```bash
bench --site jarvis.localhost console
>>> import frappe
>>> frappe.get_all("Jarvis Chat Message",
...     filters={"streaming": 1},
...     fields=["name", "conversation", "creation"])
```

Messages older than ~5 minutes are auto-cleaned by the `stale_scan` scheduler job. Force a manual scan:

```bash
bench --site jarvis.localhost execute jarvis.chat.stale_scan.scan_and_mark_errored
```

### Debug a chat turn

The plugin logs each tool call with args + result preview to the openclaw container's stdout:

```bash
cd ~/bench/develop/jarvis/openclaw
docker compose logs openclaw-gateway --since=120s | grep jarvis-openclaw-plugin
```

For a Frappe-side perspective:

```bash
bench --site jarvis.localhost console
>>> conv = frappe.get_doc("Jarvis Conversation", "JCONV-00001")
>>> for m in frappe.get_all("Jarvis Chat Message", filters={"conversation": conv.name},
...     fields=["seq","role","tool_name","tool_status","streaming","content"], order_by="seq"):
...     print(m)
```
