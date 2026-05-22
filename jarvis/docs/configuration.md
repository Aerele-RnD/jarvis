# Configuration

All Jarvis configuration lives on the **Jarvis Settings** Single DocType — accessible in Desk at `/app/jarvis-settings`. Two tabs: **Settings** (what the customer fills in) and **Operator** (the connection to your assigned container — read-only, populated for you).

## Settings tab

### Section: Jarvis Cloud connection

| Field | Type | Default | Purpose |
|---|---|---|---|
| `jarvis_admin_url` | Data | empty → falls back to the hardcoded `https://admin.jarvis.aerele.in` | The control-plane URL. **When set, `on_update` routes credential changes to the admin (production); when blank, it uses the local `openclaw_bootstrap` path (dev).** Set it only to point at a staging/alternate admin. |
| `jarvis_admin_api_key` | Password | set by onboarding | Your admin API token, returned by signup and stored automatically. Authenticates the app's calls to the control plane (`confirm_payment`, `get_connection`, `renew`, credential push). You don't set this by hand. |
| `token_budget_monthly` | Int | `0` | `0` = unlimited; otherwise an informational cap (future billing). |
| `enabled` | Check | `1` | Master switch for Jarvis features on this site |

### Section: Language Model

The customer fills these. Saving routes the change through `on_update` — to the control plane in production, or the local push in dev (see [architecture.md](architecture.md) and [local-dev.md](local-dev.md#credentials-update-flow)).

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

## Operator tab — connection (read-only)

The connection to your assigned openclaw container. **Customers don't edit these
in production** — they're populated for you:

- **Production (Jarvis Cloud):** onboarding (`onboarding.write_connection`) stores
  `agent_url` (`wss://<slug>.jarvis.aerele.in`) and `agent_token` from the
  control plane's signup/`get_connection` response. The `agent_*_path` /
  `agent_compose_dir` fields are dev-only and stay blank — the admin + fleet own
  the container files, not your site.
- **Local dev:** `bench execute jarvis.openclaw_bootstrap.start` fills all of
  them for the bench-local container (see [local-dev.md](local-dev.md)).

| Field | Type | Populated by | Used by |
|---|---|---|---|
| `agent_url` | Data | prod: signup response (`wss://…`); dev: `bootstrap.start` (`ws://127.0.0.1:18789`) | chat worker WS; `openclaw_push` (dev) |
| `agent_token` | Password | prod: signup response; dev: `bootstrap.start` generates `token_urlsafe(32)` | WS auth; `openclaw_push` (dev) |
| `agent_llm_key_path` | Data | dev only: `bootstrap.start` (`<workspace>/openclaw_state/llm.key`) | `openclaw_push.write_key_file` (dev) |
| `agent_config_path` | Data | dev only: `bootstrap.start` (`<workspace>/openclaw_state/openclaw.json`) | `openclaw_push.push_creds_restart` (dev) |
| `agent_compose_dir` | Data | dev only: `bootstrap.start` (`<workspace>/openclaw`) | `openclaw_push.restart_gateway` (dev) |

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

There is no field-level validation on save. In the dev (local-openclaw) path the `on_update` hook records `skipped: ...` in `last_sync_status` if the operator fields aren't populated, rather than rejecting the save. See [local-dev.md](local-dev.md#credentials-update-flow) for the full classification logic and which field changes trigger reload vs restart.
