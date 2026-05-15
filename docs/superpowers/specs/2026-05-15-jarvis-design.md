# Jarvis — AI Superpowers for Frappe/ERPNext (SaaS)

## Context

Frappe/ERPNext users — especially business owners and execs — struggle to get the answers and insights they need out of their ERP without going through reports, custom scripts, or another person. The schema is large, customizations are common, and the Desk UI is data-entry oriented rather than question-answering oriented. Generic AI tools (ChatGPT, Copilot) don't know the customer's schema or permissions, so they can't safely answer questions over real ERP data.

Jarvis is a SaaS that gives Frappe/ERPNext users "AI superpowers" inside their existing ERPNext install. It pairs an in-bench Frappe app (UI + MCP + permission enforcement + credential storage) with a cloud agent runtime built on **openclaw** (an AI assistant framework with a strong agent-looping mechanism). Data and credentials stay on the customer's bench; the agent brain lives in our cloud.

**Project state:** Greenfield. `/Users/venkatesh/bench/develop/jarvis` is empty (not a git repo, no code). This document is the founding spec.

**Memory directive:** This project is treated as fully independent of any other project in this workstation. No conventions, decisions, or context are inherited from sibling projects (recorded in `feedback_independent_project.md`).

---

## Product Vision (Full Scope)

The end-state product is structured in four layers, each building on the previous. **Only Layer 1 is in v1 scope.** Layers 2–4 will each get their own spec.

1. **Read & Understand (v1)** — schema-aware, permission-aware Q&A over the customer's ERPNext. Plain-English questions return text, tables, charts, and saved views. Foundation for every layer above.
2. **Proactive Layer (future)** — scheduled jobs, alerts, anomaly detection, daily/weekly digests pushed to the user.
3. **Reasoning Layer (future)** — forecasts, scenario modeling, what-if analyses, recommendations.
4. **Action Layer (future)** — agent writes back into ERPNext (drafts POs, posts entries, sends reminders) behind explicit approvals.

---

## v1 Scope (Detailed)

**Primary user:** Business owners and execs of companies running ERPNext.

**Primary job-to-be-done:** Ask plain-English questions over ERPNext data ("top 5 customers last quarter by margin", "stock turnover for Item X this year vs last", "outstanding receivables over 60 days") and get correct, grounded answers with tables, charts, and the option to pin results.

**Surface:** Embedded chat UI inside ERPNext Desk (Frappe app — Desk page and/or sidebar).

**Data scope:** All standard ERPNext DocTypes. Each DocType is described by its own **openclaw skill** that encodes the semantic context (purpose, key fields, common queries, joins, gotchas). The agent loop picks the relevant skill(s) per query rather than relying on one monolithic system prompt.

**Output formats:** Text, tables (inline, with links to underlying records), charts (bar/line/pie), and **saved views** (pin an answer to a personal dashboard).

**Conversation model:** Multi-turn within a session. No long-term per-user memory in v1 (out of scope; comes in a later spec).

**LLM cost handling:** Hybrid — subscription bundles a token budget, overage billed via metering. Pricing tiers/units are explicitly **deferred** to a later decision; v1 needs only the metering plumbing.

**Tenancy:** Per-site (per customer ERPNext install). Each install is a tenant.

---

## Architecture

### Two halves of the system

**A) Customer side — the `jarvis` Frappe app (installed on customer bench):**

- **Settings DocType** (single) — stores: openclaw tenant API key, socket endpoint, token-budget config, feature toggles.
- **MCP server** — exposes ERPNext data and operations as tools. Every call passes through Frappe's permission system tied to the *calling user*, so the AI cannot see data the user themselves cannot see. Standard DocTypes are exposed; semantic context lives on the openclaw side as skills.
- **Chat UI** — Desk page (and/or workspace widget) with conversation, table rendering, chart rendering, "pin to dashboard" action.
- **Saved Views DocType** — stores pinned answers as a personal dashboard for the user.
- **Socket client** — opens a single outbound WebSocket to openclaw cloud (no inbound ports needed; on-prem / firewalled installs work).
- **Usage metering hooks** — record token consumption per tenant per period for hybrid billing.

**B) Cloud side — openclaw-based agent runtime (our SaaS):**

- **Tenant registry** — maps API keys to tenants; tracks token budgets and overage.
- **openclaw agent loop** — orchestrates LLM calls, tool use, multi-turn context.
- **DocType skills library** — one skill per standard ERPNext DocType, describing semantics, fields, common queries, joins. The agent selects relevant skills per question.
- **MCP client** — invokes tool calls back over the customer's open socket. The customer's bench is the only place that can resolve those tool calls (since it holds the data and enforces permissions).
- **Streaming response pipeline** — streams partial answers (tokens, then structured blocks for tables/charts) back over the socket.

### End-to-end query flow

1. User types a question in the Desk chat UI.
2. Frappe backend forwards the query over the outbound WebSocket to openclaw cloud.
3. Openclaw runs its agent loop: picks relevant DocType skills, plans tool calls.
4. For each tool call, openclaw sends a tool-call message back down the **same socket**. The Frappe backend executes the call through the customer-side MCP, which enforces ERPNext permissions for the calling user, and returns the result over the socket.
5. Openclaw composes the answer (text, tables, chart specs) and streams it back over the socket.
6. Frappe backend streams to the chat UI, which renders text, tables, and charts incrementally. User can pin a result, creating a Saved View record.

### Why this shape

- **Trust pitch:** Data and credentials never leave the customer's bench except as the LLM context strictly needs to answer the question. Critical for ERPNext customers (often privacy/regulation-sensitive).
- **Firewall friendly:** A single outbound socket from the bench. No inbound exposure needed.
- **Permissions for free:** MCP calls hit Frappe's existing per-user permission system. The AI inherits the user's view of the world.
- **Composable knowledge:** A skill-per-DocType library scales better than a single mega-prompt and is easier to test and version.

---

## Critical Files & Components to Build

Greenfield — nothing to reuse. Build order:

**Customer-side (Frappe app `jarvis`):**

- `jarvis/jarvis/doctype/jarvis_settings/jarvis_settings.py` — single DocType, stores openclaw API key + endpoint + budget config.
- `jarvis/jarvis/doctype/jarvis_saved_view/jarvis_saved_view.py` — pinned answer records.
- `jarvis/jarvis/mcp/server.py` — MCP server exposing read tools (get_doc, get_list, run_report, get_schema) with permission checks.
- `jarvis/jarvis/socket/client.py` — outbound WebSocket client, handles tool-call dispatch and streaming.
- `jarvis/jarvis/page/jarvis_chat/` — Desk page with chat UI (HTML/JS), table renderer, chart renderer, pin-to-dashboard.
- `jarvis/jarvis/usage/meter.py` — per-tenant token counting hooks.

**Cloud-side (openclaw-based SaaS):**

- Tenant/auth service — API-key-keyed tenant registry, budget tracker.
- Socket gateway — accepts inbound socket connections from customer benches; multiplexes per tenant.
- openclaw runtime — agent loop, tool-use, streaming.
- DocType skills library — one skill module per standard DocType under `skills/doctypes/`.
- Billing/metering store — usage rollups for the hybrid bundled+overage model.

---

## Key Open Items (Deferred, Not Blockers)

- **Pricing model** (per-site vs per-user vs tiered) — deferred; v1 only needs the metering plumbing.
- **Long-term memory** — out of v1; revisit when proactive layer is specced.
- **Custom DocType support** — out of v1; will need a tenant-side schema-introspection skill in a later layer.
- **Multi-language support** — defer until v1 product is validated in English.
- **Cloud infra choices** (region, hosting, observability stack) — needs its own ops-focused spec before launch.

---

## Verification (How We'll Know v1 Works)

- **Install path:** Fresh ERPNext bench → `bench get-app jarvis` → install on site → open Settings DocType → enter API key → chat UI appears in Desk.
- **End-to-end query:** Logged in as a sales role user, ask "top 5 customers by sales this quarter". Receive a text answer, a table with links to Customer records, and a bar chart. Pin the answer; it appears in Saved Views.
- **Permission isolation:** A user with no access to Purchase Invoice asks "top 5 suppliers by spend". The agent should report it cannot answer due to missing permissions, never leak data.
- **Streaming:** Long answer renders progressively (tokens stream; table/chart blocks resolve when structured).
- **Multi-turn:** Follow-up "now break that down by region" uses prior context; "new chat" resets context.
- **Skill selection:** Confirm via logs that the agent invoked only the relevant DocType skills (e.g., Sales Invoice + Customer for sales queries), not all 200+ skills.
- **Usage metering:** Token counts per tenant per session are recorded and visible in an admin/usage view.
- **Firewall friendliness:** Install works on a bench with no inbound internet exposure — only outbound WebSocket required.

---

## Next Step

If approved, the next phase is to break this v1 into a sequenced implementation plan (Frappe app skeleton → MCP server → socket transport → openclaw cloud skeleton → first DocType skill → chat UI → table/chart rendering → saved views → metering → end-to-end test on a real ERPNext site).
