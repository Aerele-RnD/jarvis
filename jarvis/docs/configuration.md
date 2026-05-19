# Configuration

All Jarvis configuration lives on the **Jarvis Settings** Single DocType — accessible in Desk at `/app/jarvis-settings`. Two tabs: **Settings** (customer-facing) and **Operator** (system-managed, will move to a separate admin app in a future version).

## Settings tab

### Section: Openclaw Connection

Phase 1 fields. **Currently unused — reserved for the Phase 2.2 agent-loop transport.** Leave blank for now.

| Field | Type | Default | Purpose |
|---|---|---|---|
| `jarvis_admin_url` | Data | empty | WebSocket URL the customer's bench will eventually use to talk to its openclaw tenant for chat sessions (Phase 2.2) |
| `jarvis_admin_api_key` | Password | empty | Per-tenant token authorising those sessions (Phase 2.2) |
| `token_budget_monthly` | Int | `0` | `0` = unlimited; otherwise hard cap before overage billing kicks in. Wired up by future billing layer; currently informational only |
| `enabled` | Check | `1` | Master switch for Jarvis features on this site |

### Section: Language Model

The customer fills these. Changing any of them triggers the [credentials update flow](operations.md#credentials-update-flow).

| Field | Type | Required? | Notes |
|---|---|---|---|
| `llm_provider` | Select | Yes (to use Jarvis) | One of 12 options — see provider list below |
| `llm_model` | Data | Yes | Provider-specific model identifier (e.g. `claude-sonnet-4-6`, `gpt-4o`, `kimi-k2.6`, `llama-3.1-70b`) |
| `llm_api_key` | Password | Yes for hosted providers, blank for local | API key for the chosen provider |
| `llm_base_url` | Data | Required for `Ollama (local)`, `vLLM (local)`, `OpenAI-Compatible`; optional otherwise | Custom base URL (e.g. `http://host.docker.internal:11434/v1` for a host-side Ollama) |

**Supported `llm_provider` values** and the openclaw provider ID each maps to:

| Jarvis Settings option | openclaw `provider_id` | Notes |
|---|---|---|
| Anthropic | `anthropic` | Bundled plugin; baseUrl ships in catalog |
| OpenAI | `openai` | Bundled |
| Google Gemini | `google` | Bundled |
| Mistral | `mistral` | Bundled |
| Groq | `groq` | Bundled |
| Together AI | `together` | Bundled (OpenAI-compatible family) |
| DeepSeek | `deepseek` | Bundled (OpenAI-compatible family) |
| Moonshot (Kimi) | `moonshot` | Bundled; supports both `api.moonshot.ai/v1` and `api.moonshot.cn/v1` |
| OpenRouter | `openrouter` | Bundled |
| Ollama (local) | `ollama` | Set `llm_base_url` to your Ollama URL (commonly `http://host.docker.internal:11434/v1` from inside the openclaw container) |
| vLLM (local) | `vllm` | Set `llm_base_url` to your vLLM endpoint |
| OpenAI-Compatible | `openai_compat` | Custom-ID fallback for any OpenAI-protocol endpoint (LM Studio, Anyscale, etc.). Set `llm_base_url`. |

### Section: Sampling (collapsible)

Per-request LLM parameters. **Currently informational** — they're stored but not yet plumbed into the agent loop (that's Phase 2.2). Changing them doesn't trigger an openclaw push.

| Field | Type | Default | Range |
|---|---|---|---|
| `llm_temperature` | Float | `0.2` | 0.0 (deterministic) – 1.0 (creative). 0.2 is a good default for analytical Q&A. |
| `llm_max_output_tokens` | Int | `4096` | Provider-dependent ceiling. |

## Operator tab

System-managed fields. The customer normally doesn't touch these — they're populated by `bench execute jarvis.openclaw_bootstrap.start`. They'll move to a separate `jarvis_admin` Frappe app when that's built; today they live here for development convenience.

### Section: Openclaw Connection (operator)

| Field | Type | How it gets populated | Used by |
|---|---|---|---|
| `agent_url` | Data | `bootstrap.start` defaults to `ws://127.0.0.1:18789` | `openclaw_push.reload_secrets` |
| `agent_token` | Password | `bootstrap.start` generates `secrets.token_urlsafe(32)` on first run, persists with `db_set`. Preserved across re-runs. | `openclaw_push.reload_secrets`, openclaw config (baked plaintext into `openclaw.json`) |
| `agent_llm_key_path` | Data | `bootstrap.start` defaults to `<workspace>/openclaw_state/llm.key` | `openclaw_push.write_key_file` |
| `agent_config_path` | Data | `bootstrap.start` defaults to `<workspace>/openclaw_state/openclaw.json` | `openclaw_push.push_creds_restart` (re-renders config here) |
| `agent_compose_dir` | Data | `bootstrap.start` defaults to `<workspace>/openclaw` | `openclaw_push.restart_gateway` (runs `docker compose` from here) |

### Section: Last Sync

Readonly outcome of the most recent on_update push.

| Field | Type | What it shows |
|---|---|---|
| `last_sync_at` | Datetime (readonly) | Timestamp of the last successful push (`ok (reload)` or `ok (restart)`). Unset until the first successful push. |
| `last_sync_status` | Long Text (readonly) | One of: `ok (reload)` / `ok (restart)` / `skipped: operator config incomplete; run jarvis.openclaw_bootstrap.start first` / `failed: <ErrorType>: <message>`. Long Text so full error messages fit. |

## Where the values live

| Value | Storage |
|---|---|
| Password fields (`jarvis_admin_api_key`, `agent_token`, `llm_api_key`) | Encrypted at rest in Frappe's `__Auth` table. Reachable via `settings.get_password("...")` for decryption. |
| All other Single fields | `tabSingles` table in the site DB |
| Rendered openclaw config (plaintext, including a copy of the gateway token) | `<workspace>/openclaw_state/openclaw.json`. Gitignored. Recreated by `bootstrap.start` and on any provider/model/base_url change. |
| LLM API key (plaintext, for openclaw to read at runtime) | `<workspace>/openclaw_state/llm.key`. Mounted into the container at `/home/node/.openclaw/llm.key`. File mode `0600`. Rewritten on every `push_creds_reload` or `push_creds_restart`. |

## Validation

There is no field-level validation on save. The `on_update` hook will detect incomplete operator config and record `skipped: ...` in `last_sync_status` rather than rejecting the save. See [operations.md](operations.md#credentials-update-flow) for the full classification logic and which combinations of field changes trigger which actions.
