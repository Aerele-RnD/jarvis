# Chat-subscription (CLI-OAuth) providers — integration & test backlog

> Goal: offer **all** integrable chat-subscription providers in onboarding (OpenAI,
> Google, Grok, Qwen, …), not just OpenAI. This is the backlog + per-provider
> plan. Date: 2026-07-07. Prompted by the onboarding review (PR #231), where the
> dropdown offered "Google" but the backend returned *"OAuth not supported for
> provider 'Google'"*.

## Two credential paths (a provider must be supported on the path we ship)

- **openclaw-direct (live today).** The OAuth runtime lives in the openclaw image;
  adding a provider needs (a) an openclaw runtime/CLI-backend for it, and (b) a
  branch in the fleet-agent template. Template
  `jarvis-fleet-agent/.../templates/openclaw.json.j2` has exactly 3 branches:
  `openai-codex`, `google-gemini-cli`, and an API-key `else`. Blob writer
  `auth_profiles.py` is provider-generic except the hardcoded `gemini_cli.py`
  bridge (writes gemini-cli's own `~/.gemini/oauth_creds.json`). Any CLI-backend
  provider that reads creds from its own file needs an analogous bridge.
- **cliproxy / CLIProxyAPI (managed pool, newer — the "all providers" enabler).**
  A CLIProxyAPI sidecar auto-discovers OAuth blobs and load-balances them; Bifrost
  fronts it. Upstream **CLIProxyAPI supports 8 CLI subscriptions** (Codex, Gemini
  CLI, Antigravity, Claude Code, Qwen Code, iFlow, Kimi, Grok/xAI). But Jarvis's
  `llm-proxy` renderer is narrower — `src/llm_proxy/schema.py` hard-codes
  `upstream: Literal["openai","anthropic","google"]` and
  `render/subscription.py` `_AUTH_PREFIX = {openai:"codex-", google:"antigravity-",
  anthropic:"claude-"}`. **This Literal is the single choke point** — generalize
  it once and Grok/Qwen/Kimi/iFlow all become expressible.

**Allowlists to edit per provider (customer side):**
`jarvis/oauth/providers.py` `_PROVIDER_OAUTH_MAP` · `jarvis/_subscription_models.py`
`SUBSCRIPTION_MODELS`/`DEFAULT_MODEL` (+ JS mirrors in `LlmPoolEditor.vue`) ·
admin `jarvis_admin/fleet/llm_providers.py` `SUBSCRIPTION_PROVIDERS` ·
`jarvis/hooks.py` `OAUTH_CLIENT_IDS` + secret.

## Already fixed in PR #231
- Google label bug: frontend sent `"Google"`; backend key is `"Google Gemini"`.
  Dropdown label + `startConnect` now send `"Google Gemini"`.
- Gemini model-suggestion drift: now `gemini-2.5-pro / gemini-2.5-flash /
  gemini-3.1-flash` (backend-valid set).

## Backlog

| Provider | CLI-OAuth sub? | Supportable via | Jarvis status | Models | Blockers / notes |
|---|---|---|---|---|---|
| **OpenAI / ChatGPT Codex** | Yes (paid; free ≈ useless) | cliproxy ✅ + openclaw ✅ | **Integrated & live-verified** | gpt-5.5, gpt-5.4, gpt-5.4-mini | chatgpt.com throttling has no clean 429 |
| **Google Gemini** | Yes | openclaw ✅ (gemini-cli); cliproxy ✅ (as **Antigravity**) | **Coded (openclaw); cliproxy leg unverified** | gemini-2.5-pro/flash, gemini-3.1-flash | `accountId` extraction returns "" for non-OpenAI; **gemini-cli vs Antigravity are different Google creds** — pick one for the pool |
| **xAI / Grok** | **Yes** (SuperGrok / X Premium+) | cliproxy ✅ (`--xai-login`) + openclaw ✅ (`xai`) | **Not started (recommended #1)** | grok-4.3, grok-build-0.1 | OAuth may be tier-gated even with active sub; api.x.ai/v1 |
| **Qwen** | Yes | cliproxy ✅ (`--qwen-login`) + openclaw ✅ (`qwen-oauth`) | **Not started (recommended #2)** | qwen3.5-plus, qwen3-coder | schema Literal lacks `qwen`; cheap/coding tier |
| **Kimi / Moonshot** | Yes | cliproxy ✅ only (openclaw = API-key) | **Not started (defer)** | kimi-k2.6 | cliproxy-only for subscription |
| **iFlow** | Yes | cliproxy ✅ only | **Not started (defer)** | — | niche; openclaw-direct unsupported |
| **Anthropic / Claude** | Yes (Claude Code) | tech-possible | **BLOCKED — ToS** | — | **Do NOT pool** (Anthropic ToS, suspensions enforced 2026-04-04; already banned in `llm_proxy/validate.py`). Claude = API-key only. |

Auth-dir filename prefixes for xai/qwen/kimi/iflow are inferred from CLIProxyAPI's
`<flag-stem>-<ref>.json` convention — **verify against a real login before wiring**
(only `codex-`/`antigravity-`/`claude-` are confirmed in Jarvis today).

## Tasks (in priority order)

- [ ] **Grok / xAI (#1).** openclaw.json.j2: add an `xai` renderer branch (mirror
      gemini-cli; base `api.x.ai/v1`); add a `grok_cli.py` bridge if the image's
      `xai` runtime reads `~/.grok/auth.json`. Customer allowlists: add `"xAI"` to
      `_PROVIDER_OAUTH_MAP` (accounts.x.ai device-code), `SUBSCRIPTION_MODELS`
      (`grok-4.3`), admin `SUBSCRIPTION_PROVIDERS`, `OAUTH_CLIENT_IDS`, JS mirrors.
      cliproxy (optional): extend schema Literal + `_AUTH_PREFIX["xai"]`.
      **Test:** `--xai-login` (or openclaw `models auth login --provider xai`) with
      a real SuperGrok account in a scratch container → non-empty `/v1/models` →
      one e2e chat turn (e2e-feature skill). Watch for tier-gated-OAuth 403.
- [ ] **Qwen (#2).** Same shape; openclaw provider `qwen-oauth` (base
      portal.qwen.ai/v1). Low ToS risk, good cheap-tier complement.
- [ ] **Finish Google Gemini managed-pool leg (#3).** Decide pooled Google =
      gemini-cli or Antigravity; either change `_AUTH_PREFIX["google"]` to
      `gemini-` or add `--antigravity-login` provisioning. Verify one Gemini turn
      through Bifrost→CLIProxyAPI + validate `accountId` handling.
- [ ] **Generalize `llm_proxy` `upstream` Literal** (cross-cutting prerequisite):
      Literal → validated set + per-upstream `_AUTH_PREFIX`, so new providers don't
      each need a schema edit.
- [ ] **Kimi / iFlow (#4, defer).** cliproxy-only; add opportunistically after the
      schema is generalized.
- [ ] **Onboarding UX:** surface that a **paid** subscription tier is required
      (free ChatGPT accounts were empirically near-useless).

## Key references
- openclaw-direct: `jarvis-fleet-agent/.../templates/openclaw.json.j2`, `auth_profiles.py`, `gemini_cli.py`
- managed-pool: `llm-proxy/src/llm_proxy/{schema.py, validate.py, render/subscription.py}`, `docs/reference/spike-findings-subscription.md`
- allowlists: `jarvis/oauth/providers.py`, `jarvis/_subscription_models.py`, `jarvis/hooks.py`, `jarvis_admin/fleet/llm_providers.py`
- upstream: CLIProxyAPI (github.com/router-for-me/CLIProxyAPI), docs.openclaw.ai/providers/{xai,qwen}, x.ai/news/grok-openclaw

**Honesty note:** only the Codex leg is proven live in Jarvis; the Gemini
managed-pool leg and every other provider are unverified in Jarvis. CLIProxyAPI's
provider support is confirmed from upstream docs; openclaw Grok/Qwen support is in
openclaw docs but not tested against Jarvis's pinned image — check the pinned
image's runtime registry first.
