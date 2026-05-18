# Development

How to set up Jarvis for development, run its tests, navigate the code, and add new tools or LLM providers.

## Setting up a dev bench

You need a working Frappe v15+ bench (Frappe v17-dev is what this app is developed against). If you already have one, skip to "Install Jarvis." Otherwise:

```bash
# 1. Init a bench (downloads Frappe, builds the env)
bench init <bench-name> --frappe-branch develop
cd <bench-name>

# 2. Get ERPNext (Jarvis relies on Frappe + ERPNext DocTypes for tests)
bench get-app erpnext --branch develop

# 3. Create a site
bench new-site jarvis.localhost --install-app erpnext --admin-password admin

# 4. Set developer mode (required for DocType JSON to load from app folders)
bench --site jarvis.localhost set-config developer_mode 1
```

### Install Jarvis

```bash
# From the bench root:
bench get-app https://github.com/Aerele-RnD/jarvis --branch main
bench --site jarvis.localhost install-app jarvis
```

For local development with edits, clone or symlink the app source into `apps/jarvis/` instead and `pip install -e` it into the bench env:

```bash
git clone git@github.com:Aerele-RnD/jarvis.git apps/jarvis
./env/bin/pip install -e apps/jarvis
bench --site jarvis.localhost install-app jarvis
```

Now `bench start` and visit `http://jarvis.localhost:8000/app/jarvis-settings`.

## Running tests

```bash
# Full app suite (~204 tests)
bench --site jarvis.localhost run-tests --app jarvis

# Single test module
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_get_schema

# Single test method (use the dotted path)
bench --site jarvis.localhost run-tests --app jarvis \
  --module jarvis.tests.test_get_schema \
  --test test_returns_fields_for_known_doctype
```

What each test module covers:

| Module | Lines under test |
|---|---|
| `tests.test_settings` | DocType structure (Single, fields, fieldtypes, Password protection, provider Select options, Operator tab fields) |
| `tests.test_exceptions` | `JarvisError` hierarchy + message passing |
| `tests.test_get_schema` | `get_schema` happy path, field shape, unknown DocType, child-table expansion |
| `tests.test_get_doc` | `get_doc` happy path, missing args, unknown doc, per-record permission isolation. Creates Customer Group/Territory fixtures because ERPNext requires non-group leaf records. |
| `tests.test_get_list` | `get_list` returns rows, limit cap, missing DocType, permission denial |
| `tests.test_run_report` | `run_report` permission denial, unknown report, missing arg; happy path skipped when no default company |
| `tests.test_run_query` | `run_query` validation (SELECT-only, no comments, no DML, `tab<DocType>` tables), DocType-level perm checks, LIMIT clamping, happy path |
| `tests.test_registry` | `dispatch` happy path, unknown tool, non-dict args, missing kwargs translation |
| `tests.test_api` | `call_tool` HTTP envelope (standard Frappe-auth path + Path A v2 plugin-auth path with `X-Jarvis-Token` + `X-Jarvis-Session` → Frappe resolves user via Jarvis Chat Session) |
| `tests.test_chat_session` | Jarvis Chat Session DocType structure + sessionKey-uniqueness |
| `tests.test_openclaw_config` | Provider mapping, JSON validity, SecretRef shape, stub fallback, all 12 providers render, Path A plugin entry present, no MCP block |
| `tests.test_openclaw_push` | File writes (0600), WebSocket frame contents, error translation, docker subprocess args |
| `tests.test_openclaw_bootstrap` | Path defaults, token generation, idempotency, env file contents, subprocess ordering |
| `tests.test_settings_on_update` | Change classification, operator gate, status recording, failure handling, key persistence on failure |
| `tests.test_jarvis_conversation` | Jarvis Conversation DocType — schema, owner-only perms, before_insert default for last_active_at |
| `tests.test_jarvis_chat_message` | Jarvis Chat Message DocType — schema, parent link, tool fields, owner-only perms |
| `tests.test_chat_policy` | `policy.validate_can_send` accept/reject (stub today; Phase 3 fills in) |
| `tests.test_chat_events` | openclaw event parsing (lifecycle/tool/assistant); `publish_to_user` wrapper |
| `tests.test_chat_openclaw_client` | Python WS client — connect handshake, sessions.create, stream_agent_turn (with mocked socket) |
| `tests.test_chat_api` | list/get/create/archive/send_message endpoints — validation, persistence, enqueue |
| `tests.test_chat_worker` | `run_agent_turn` — happy path, tool events, error paths (with mocked OpenclawSession) |
| `tests.test_chat_stale_scan` | stale-streaming scan job |
| `tests.test_api_chat_session_header` | `call_tool` X-Jarvis-Session header behaviour |

Tests run against the live `jarvis.localhost` site (Frappe's `FrappeTestCase` requires a real site for DB access). Bench Redis must be running on ports 11000 / 13000 — if you see `Should not fail silently in tests`, that's a missing Redis instance; `bench start` brings them up.

## Project structure

```
app/
├── pyproject.toml                            # flit build, ruff config, deps
├── README.md
├── license.txt
├── .editorconfig, .eslintrc, .pre-commit-config.yaml, .gitignore
└── jarvis/                                   # the Python package
    ├── __init__.py
    ├── hooks.py                              # Frappe app metadata
    ├── modules.txt                           # contains: Jarvis
    ├── patches.txt                           # pre/post-migrate hook sections
    ├── api.py                                # @frappe.whitelist call_tool endpoint
    ├── exceptions.py                         # JarvisError hierarchy
    ├── openclaw_config.py                    # render_config + PROVIDER_MAP + STUB_DEFAULTS
    ├── openclaw_push.py                      # write_key_file, reload_secrets, restart_gateway, push_creds_*
    ├── openclaw_bootstrap.py                 # start, stop, status, restart bench commands
    ├── openclaw_templates/openclaw.json.j2   # Jinja template for openclaw config
    ├── docs/                                 # this directory
    ├── tools/
    │   ├── __init__.py
    │   ├── registry.py                       # dispatch + list_tools
    │   ├── get_schema.py
    │   ├── get_doc.py
    │   ├── get_list.py
    │   ├── run_report.py
    │   └── run_query.py                      # SELECT-only SQL for joins / aggregates
    ├── config/__init__.py                    # Frappe boilerplate
    ├── patches/__init__.py
    ├── templates/
    │   ├── __init__.py
    │   └── pages/__init__.py
    ├── public/.gitkeep                       # frontend assets (Phase 2.2+)
    ├── jarvis/                               # the Frappe "module" (per modules.txt)
    │   ├── __init__.py
    │   ├── .frappe                           # Frappe v17 module marker
    │   └── doctype/
    │       └── jarvis_settings/
    │           ├── __init__.py
    │           ├── jarvis_settings.json      # Single DocType definition
    │           └── jarvis_settings.py        # validate() + on_update() controller
    └── tests/
        ├── __init__.py
        └── test_*.py                          # 12 test modules
```

The double-named `jarvis/jarvis/` nesting is a Frappe convention: the outer `jarvis/` is the Python package (matches `app_name` in `hooks.py`); the inner `jarvis/` is the Frappe "module" (matches the entry in `modules.txt`). DocTypes must live under the module directory because Frappe imports them as `<app>.<module>.doctype.<doctype>.<controller>`.

General-purpose code (`tools/`, `api.py`, `exceptions.py`, `openclaw_*`, `tests/`) lives at the package root for cleaner imports (`from jarvis.tools.registry import dispatch`, not `from jarvis.jarvis.tools.registry...`).

## Recipes

### Adding a new tool

1. **Write the tool** at `app/jarvis/tools/<tool_name>.py`. Single public function. Validate args with `InvalidArgumentError`. Check permissions with `frappe.has_permission(...)` and raise `PermissionDeniedError`. Examples: any existing tool in `tools/`.
2. **Register** in `app/jarvis/tools/registry.py`:
   ```python
   from jarvis.tools.<tool_name> import <tool_name>
   _TOOLS = { ..., "<tool_name>": <tool_name>, }
   ```
3. **Write tests** at `app/jarvis/tests/test_<tool_name>.py`. Cover: happy path, empty args, unknown target, permission denial. Use `FrappeTestCase`.
4. **Update `test_registry.test_list_tools_contains_all_*`** to include the new tool name.
5. **Document** in [`docs/tools-api.md`](tools-api.md) — add a section under "The five tools".

### Adding a new LLM provider

1. **Add to the Jarvis Settings dropdown.** Edit `app/jarvis/jarvis/doctype/jarvis_settings/jarvis_settings.json`. Find the `llm_provider` field, append the new option to its newline-separated `options` string (and add to `EXPECTED_PROVIDERS` in `test_settings.py`).
2. **Add to the openclaw mapping.** Edit `PROVIDER_MAP` in `app/jarvis/openclaw_config.py`:
   ```python
   PROVIDER_MAP = { ..., "New Provider": "new_provider_id", }
   ```
   Use openclaw's exact provider id (lowercase, matches the regex `^[a-z][a-z0-9_-]{0,63}$`). If the provider isn't bundled in openclaw, choose a custom id and use openclaw's OpenAI-compatible defaults (set `baseUrl` in Jarvis Settings).
3. **Add a test case** in `app/jarvis/tests/test_openclaw_config.py` → `TestRenderConfig.test_all_twelve_providers_render` (rename the test or just extend the cases dict).
4. **Migrate** so the new Select option lands in the DB:
   ```bash
   bench --site jarvis.localhost migrate
   ```

## Code style

- **Ruff** is the formatter and linter. Config lives in `pyproject.toml` under `[tool.ruff]` — `line-length = 110`, tab indentation, `target-version = "py310"`. Run `ruff check` and `ruff format` (or let pre-commit run them on commit).
- **Tab indentation** for Python — matches the Frappe convention captured in `.editorconfig`.
- **No emojis** in code or comments unless explicitly requested.
- **Pre-commit** runs ruff (linter + import-sort + formatter), prettier (JS/SCSS), eslint (JS), and trailing-whitespace / json-validity checks. Install with `pre-commit install` from inside `apps/jarvis/`.

## Where design docs live

The "why" behind Jarvis (the four-layer product vision, the detailed Phase 1 + Phase 2.1 specs, the implementation plans, the verification runbooks) lives in the workspace-level docs directory at `<workspace>/docs/superpowers/`. That tree is **intentionally not in this repo** — it's local design history kept separate from the public app code.

If you need that context (e.g. for understanding why a particular field exists or why we chose `secrets.reload` over `docker restart` for key changes), you'll find it in:

- `<workspace>/docs/superpowers/specs/2026-05-15-jarvis-design.md` — the original product spec
- `<workspace>/docs/superpowers/plans/2026-05-15-jarvis-foundation.md` — Phase 1 implementation plan
- `<workspace>/docs/superpowers/plans/2026-05-15-jarvis-credentials-update-stack.md` — Phase 2.1 plan
- `<workspace>/docs/superpowers/verification/2026-05-15-jarvis-credentials-update-stack.md` — Phase 2.1 verification runbook

These are workspace-only artefacts; they don't ship with the app.
