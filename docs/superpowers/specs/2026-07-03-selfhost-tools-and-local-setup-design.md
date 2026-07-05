# Self-Hosted openclaw — tool-path validation + easy local setup — Design

Date: 2026-07-03
Status: proposed
Apps: `jarvis` (customer Frappe app) + `selfhost-standalone/` (BYO local openclaw scaffold)
Supersedes the "out of scope" notes in `2026-06-18-self-hosted-openclaw-design.md` §Out-of-scope (the ERP-tools increment has since shipped).

## Context / problem

Self-hosted (BYO) openclaw is the open-source path: the user brings their own
openclaw runtime + their own LLM; **Aerele's persona/skills stay on the Managed
(paid) path**. A later increment added ERP tools to self-host (`jarvis__*` via
the plugin, running as `selfhost_tool_user`). Three gaps remain:

1. **Stale docs.** `jarvis/selfhost.py:14` still says *"v1 = connect + chat. ERP
   tools … out of scope"* — contradicted by the same file's `selfhost_tool_user`
   + tool-card code. The 2026-06-18 spec likewise lists tools as out-of-scope.
2. **Validation never checks the tool path.** "Test connection" verifies
   reachable/auth/llm only. A user can go all-green yet have every `jarvis__*`
   call fail — most commonly because `selfhost_tool_user` is unset, or the
   user's openclaw can't network-reach the Frappe callback URL.
3. **No turnkey local setup.** `selfhost-standalone/` has only an `entrypoint.sh`
   + a materialized state — no compose/README showing how to run openclaw + the
   plugin (no persona/skills) and point Jarvis at it.

## Hard constraint

**Do not change the Managed flow.** Every new code path is either self-host-only
(guarded by `selfhost.is_self_hosted()`) or a new function not on the managed
turn path. No change to the shared plugin, `turn_handler`, or managed transport.
`tests/test_selfhost.py` + the managed chat tests must both stay green.

## Decisions (locked)

- **No plugin change, no new `jarvis__*` tool.** The callback probe reuses an
  existing read-only tool (`get_schema`) and confirms delivery via a cache
  marker written *only* in `call_tool`'s self-host branch. Keeps the shared
  plugin (and therefore managed) untouched, and needs no plugin rebuild/redeploy.
- **Persona/skills stay excluded** from the standalone scaffold — plugin + tools
  only. (Reaffirms the paid/open-source split.)
- **Local scaffold = Docker Compose + README** (recommended path), pulling the
  public `ghcr.io/openclaw/openclaw:latest`.

## Part 1 — Docs correction (no behavior change)

- `jarvis/selfhost.py` module docstring: replace the "v1 = connect + chat / tools
  out of scope" line with an accurate summary (tools supported via the plugin +
  `selfhost_tool_user`; persona/skills remain Managed-only).
- `docs/superpowers/specs/2026-06-18-self-hosted-openclaw-design.md`: add a dated
  **addendum** at the top noting the ERP-tools increment shipped and pointing to
  this spec. Don't rewrite the original (preserve history).

## Part 2 — Validation improvements (`jarvis/selfhost.py`)

Keep `validate_connection(base_url, token, *, deep=False)` **pure** (openclaw
HTTP only) and unchanged in contract. Add two isolated units + compose them in
the whitelisted wrappers.

### 2a. Deterministic config checks (always run, no network, no LLM)

New helper `config_checks(tool_user: str | None) -> list[dict]` returning
`{check, ok, detail}` rows:

- `tool_user` — resolves to a set, **non-admin, enabled** Frappe user. Reuses the
  exact invariant in `api._selfhost_tool_user` (never Administrator/Guest/missing/
  disabled). `tool_user` arg falls back to the stored `selfhost_tool_user`.
- `gateway_token` — the bearer token is non-empty.

These are **advisory** in `test_connection` (surface red/green in the UI) and the
`tool_user` check becomes a hard requirement in `save_self_hosted` (it already
rejects a bad tool user — this just unifies the reporting).

### 2b. Opt-in callback probe (`deep_tool`) — post-save / re-test only

New function `probe_tool_callback(base_url, token) -> dict`:

- **Precondition:** only runs when `is_self_hosted()` is already true (the
  callback's `call_tool` self-host branch requires it). Pre-save `test_connection`
  reports the probe as `skipped` with detail "save self-host mode first, then
  re-test from My Account". This avoids a false-fail during onboarding.
- **Mechanism (LLM-induced, marker-confirmed):**
  1. Read the current marker `frappe.cache().get_value("jarvis:selfhost_calltool_seen")`
     as `t0` (may be None).
  2. POST `{base}/v1/chat/completions` (non-stream) with a directive prompt:
     *"Call the jarvis__get_schema tool for the 'User' doctype, then reply DONE."*
  3. Re-read the marker. If it advanced past `t0` (or went None→set) within the
     window → `callback_probe ok=True` ("openclaw→Frappe callback confirmed").
     If unchanged → `ok=False, detail="no callback observed (model may not have
     called the tool, or openclaw can't reach {frappe_url})"`.
- **Best-effort:** never required for `ok`; a negative result is informational
  (the model declining to call a tool ≠ a broken callback). Timeout reuses the
  deep budget.

### 2c. The marker write (`jarvis/api.py`, self-host branch only)

In `call_tool`, inside the existing `if selfhost.is_self_hosted():` self-host
branch (after the gateway token is validated and `plugin_user` resolves), write a
best-effort cache marker:

```python
selfhost.note_callback_seen()   # frappe.cache().set_value(_CALLTOOL_SEEN_KEY, now_ts, expires_in_sec=...)
```

`note_callback_seen()` lives in `selfhost.py`, wrapped in
`contextlib.suppress(Exception)` (cosmetic; never fail a real tool call on a
cache blip). **This is the only edit to a shared code path, and it is inside the
self-host-only branch — managed never executes it.**

### 2d. Wrapper wiring

- `test_connection(base_url, token, deep, deep_tool=0, tool_user="")` — runs
  `validate_connection` (+ optional `deep`), appends `config_checks(...)`, and if
  `deep_tool` appends `probe_tool_callback(...)` (or the `skipped` row). Returns
  the merged `checks` array. System-Manager gated (unchanged).
- `save_self_hosted(...)` — unchanged required-check semantics; the `tool_user`
  reporting is unified via `config_checks` but the existing hard reject stays.

## Part 3 — Local setup scaffold (`selfhost-standalone/`)

Files (all new except `entrypoint.sh`, which is reused as-is):

- **`docker-compose.yml`** — one `openclaw` service:
  - `image: ghcr.io/openclaw/openclaw:latest`
  - volumes: `${JARVIS_PLUGIN_PATH}:/home/node/.jarvis-plugin:ro`,
    `./openclaw.json:/home/node/.openclaw/openclaw.json:ro`,
    `openclaw_state:/home/node/.openclaw` (named volume for writable state),
    `./entrypoint.sh:/usr/local/bin/jarvis-entrypoint.sh:ro`.
    **No persona mount, no skills.**
  - env from `.env`: `OPENCLAW_GATEWAY_TOKEN`, `JARVIS_GATEWAY_TOKEN`
    (= gateway token), `JARVIS_FRAPPE_URL`, `JARVIS_SITE_NAME`, plus the user's
    LLM key var (e.g. `OPENAI_API_KEY`).
  - `extra_hosts: host.docker.internal:host-gateway` (so openclaw in Docker can
    reach a Frappe bench on the host).
  - ports: `${GATEWAY_PORT:-19060}:18789`.
  - `entrypoint: /usr/local/bin/jarvis-entrypoint.sh`; `command: node openclaw.mjs
    gateway --bind lan --port 18789 --allow-unconfigured --token ${OPENCLAW_GATEWAY_TOKEN}`.
  - healthcheck: fetch `http://127.0.0.1:18789/healthz`.
- **`openclaw.json`** — minimal working config: `gateway` (token auth, port
  18789), `plugins.load.paths:["/home/node/.jarvis-plugin"]` +
  `entries.jarvis-openclaw-plugin.enabled:true`, `tools.toolSearch.mode:"directory"`,
  and a **commented example** `models.providers` block the user fills for their
  own LLM. **No `agents.defaults.skills`, no persona.**
- **`.env.example`** — every var above with placeholders + inline comments.
- **`README.md`** — the fresh-user flow:
  1. `git clone` + `pnpm install && pnpm build` the plugin; set `JARVIS_PLUGIN_PATH`.
  2. `cp .env.example .env`; fill gateway token, `JARVIS_FRAPPE_URL`,
     `JARVIS_SITE_NAME`, LLM key.
  3. `docker compose up -d`; confirm `/healthz`.
  4. In Jarvis → Self-Hosted mode: paste URL (`http://host.docker.internal:19060`
     or `http://localhost:19060`) + gateway token → Test connection → set
     Self-Host Tool User → (re-test with the tool probe) → chat.

## Data flow (unchanged transport; new checks only)

```
Test connection (pre-save):
  Frappe → openclaw: /healthz, /v1/models         (validate_connection)
  Frappe (local):    tool_user + gateway_token     (config_checks)
  probe:             skipped (not self-host yet)

Re-test (post-save, deep_tool=1):
  Frappe → openclaw: /v1/chat/completions "call jarvis__get_schema"
  openclaw(plugin) → Frappe: /api/method/jarvis.api.call_tool  (X-Jarvis-Token)
     └─ self-host branch: runs as selfhost_tool_user, writes calltool marker
  Frappe: marker advanced? → callback_probe ok
```

## Testing

- **Unit (`tests/test_selfhost.py`, extend):**
  - `config_checks`: tool_user set/unset/Administrator/Guest/disabled/missing;
    token present/blank.
  - `probe_tool_callback`: mocked HTTP + mocked cache — marker advances → ok;
    unchanged → not-ok; not self-host → skipped.
  - `note_callback_seen`: writes the marker; suppresses cache errors.
  - `validate_connection`: unchanged tests stay green (contract preserved).
- **Managed regression:** existing managed chat tests + `call_tool` plugin-auth
  (session-mapped) tests stay green; assert the marker is NOT written on the
  managed/session path.
- **Manual acceptance:** stand up the `selfhost-standalone` compose against a
  local bench; Test connection green; set tool user; re-test → callback_probe ok;
  send a chat that triggers a `jarvis__*` tool and confirm real ERP data +
  a tool card.

## Out of scope

- Any change to the shared `jarvis-openclaw-plugin` (no new tool, no rebuild).
- Managed-mode behavior of any kind.
- Jarvis-side LLM push to the user's openclaw (LLM stays user-side).
- Persona/skills for self-host (stays Managed-only, by decision).

## Risks

- The `deep_tool` probe is LLM-gated: a model that declines to call the tool
  yields a false-negative. Mitigated by wording it as advisory + the deterministic
  `tool_user`/`gateway_token` checks catching the common real failures.
- openclaw HTTP surface drift — checks pin to documented endpoints
  (`/healthz`, `/v1/models`, `/v1/chat/completions`).
