# Decision: Identity propagation — registered openclaw plugin tools (Path A)

**Date:** 2026-05-17
**Phase:** 2.2.a
**Status:** Adopted and shipped

---

## Problem

Jarvis tools execute against ERPNext data. Every tool call must run under the
permissions of the specific Frappe user who initiated the conversation — not as
Administrator, not as Guest. Without per-user identity at tool-call time,
Frappe cannot apply DocType-level or row-level permission checks, and the
principle of least privilege is violated.

The identity must flow from the Frappe side (which knows the user because the
chat session was initiated there) → through openclaw (which manages the agent
loop and fires the tool calls) → back to Frappe (which actually runs the tool).

The original plan: expose Jarvis tools as an **MCP server** at
`jarvis.mcp.serve`, with a `before_tool_call` plugin hook in
`jarvis-openclaw-plugin` injecting `_user` into the tool params before they
reached Frappe. We tried four variants of that plan. All four hit hard
architectural walls in openclaw — not bugs in our code, but structural facts
about how openclaw's plugin SDK exposes session context to *MCP-routed* tools
today.

This document captures what we tried, why each variant failed, and why we
landed on registered plugin tools (Path A) — the same pattern openclaw's
bundled chat channels already use.

---

## Four MCP+hook approaches and why each failed

### Attempt 1 — `getSessionExtension` in the hook ctx

**Plan:** At session-create, stamp the user into the session's extension
namespace (registered via `api.session.state.registerSessionExtension`). The
hook reads it via `ctx.getSessionExtension("requesterSenderId")`.

**Wall:** `ctx.getSessionExtension` does not exist on the regular
`before_tool_call` hook context. It is only on the *trusted-tool-policy*
context — a different code path. At runtime,
`ctx.getSessionExtension?.("requesterSenderId")` silently returns `undefined`.

The relevant openclaw source: `pi-tools.before-tool-call.ts` (~lines 525–534).
`PluginHookToolContext` and `TrustedToolPolicyContext` are distinct types.

### Attempt 2 — register a trusted-tool-policy instead

**Plan:** Since `getSessionExtension` lives on the trusted-tool-policy context,
register a trusted-tool-policy in the plugin and use that context shape.

**Wall:** Trusted-tool-policy registration is gated to plugins with
`origin === "bundled"` (`openclaw/src/plugins/registry.ts:1837–1849`):

```typescript
if (origin !== "bundled") {
  throw new PluginRegistrationError(
    "trusted tool policies can only be registered by bundled plugins"
  );
}
```

`jarvis-openclaw-plugin` is a third-party extension. Its origin is
`"extension"`, not `"bundled"`. There is no opt-in flag or capability grant.
The check is hard-coded.

### Attempt 3 — `requesterSenderId` via factory ctx (wrong reading at the time)

**Plan:** Use the registered-tool factory mechanism, where the factory
receives an `OpenClawPluginToolContext` that exposes `requesterSenderId`.

**Wall as we first hit it:** `requesterSenderId` is `undefined` for
gateway-client / backend-initiated agent runs. It is only populated by
channel-ingress paths (Telegram bot receives a message → session created with
sender; same for Slack, WhatsApp, Discord). The demo command uses the `agent`
RPC on a gateway-client WS connection, which is "backend-initiated".

**We dismissed this approach prematurely.** We assumed identity propagation
through the factory ctx required `requesterSenderId`. It does not — the
factory ctx also exposes `sessionKey`, which IS populated for every run. See
Resolution below.

### Attempt 4 — sessionKey + Frappe HTTP lookup, injected via hook

**Plan:** Use `ctx.sessionKey` (which IS present in the hook context per the
documented `PluginHookToolContext` type) plus an HTTPS lookup to a
`jarvis.api.lookup_user_by_session` endpoint that maps sessionKey → user via a
`Jarvis Chat Session` DocType row inserted at session-create time.

The plumbing was built end-to-end: lookup endpoint, DocType, plugin hook with
HTTP fetch + in-memory cache, plugin env vars wired via
`openclaw_bootstrap._write_env_file`. All unit tests passed.

**Wall:** **`ctx.sessionKey` is also missing from the hook event when the
tool is routed through MCP.** The relevant openclaw call site is
`openclaw/src/agents/pi-tool-definition-adapter.ts:241`:

```typescript
// MCP-routed tools — the call site that fires for our jarvis__* tools
const hookOutcome = await runBeforeToolCallHook({
  toolName: name,
  params,
  toolCallId,
  // ← no ctx passed
});
```

Compare line 346 in the same file, which DOES pass `ctx: hookContext` for
non-MCP / locally-registered tools.

Live evidence from the demo run on 2026-05-17: the agent invoked
`jarvis__get_list`. The plugin's hook fired. It logged
`no sessionKey in ctx for tool=jarvis__get_list` and returned undefined. The
tool call reached Frappe without `_user` and was rejected with
`missing or invalid _user (must be injected by jarvis-openclaw-plugin hook)`.

**Root cause:** The MCP adapter constructs the before_tool_call event with
only `{toolName, params, toolCallId}`. There is no `hookContext` available at
that call site to forward; the MCP path was not designed to participate in
the plugin hook's session-context contract.

---

## Why Telegram, Slack, Discord, WhatsApp don't have this problem

Critical realization from reading openclaw's bundled channel implementations:
**chat channels do not expose their functionality as MCP servers.** They are
registered openclaw plugin tools, on the "factory" code path.

Two code paths inside openclaw:

| Path | Used by | Hook ctx | Factory ctx |
|---|---|---|---|
| **Factory path** (registered plugin tools) | telegram, slack, discord, whatsapp, openclaw's own message/memory tools | full `PluginHookToolContext` with sessionKey, requesterSenderId, agentId, channelId, etc. | full `OpenClawPluginToolContext` |
| **MCP path** (external MCP servers in `mcp.servers.*`) | what Jarvis chose | only `{toolName, params, toolCallId}` — no session context | n/a (MCP doesn't have a factory; it's a black-box JSON-RPC forwarder) |

When an openclaw-powered Telegram bot's agent invokes
`message__send_to_user`, that tool is registered through the factory path.
The factory ctx includes the inbound `requesterSenderId` (the Telegram user's
id), and the tool implementation uses it to know which chat to send the reply
to. Identity propagation Just Works because openclaw built its own tools
through the path it designed.

Concrete openclaw code references:

- `src/agents/pi-tools.ts:807` — `requesterSenderId: options?.senderId` when
  invoking a registered tool from the Pi runtime.
- `src/agents/tools/message-tool.ts:549–930` — openclaw's own send-message
  tool reads `requesterSenderId` from options.
- `src/plugins/tool-types.ts:14–51` — `OpenClawPluginToolContext` exports
  `sessionKey`, `requesterSenderId`, `agentId`, `deliveryContext`,
  `senderIsOwner`, etc. All the fields a tool factory needs to behave
  per-user.
- `src/agents/pi-tool-definition-adapter.ts:241` vs `:346` — the two
  divergent before_tool_call invocations.

Jarvis was on the path that openclaw did not design for per-user identity.
Every approach we tried was structurally blocked at the same boundary.

---

## Resolution — Path A: Jarvis tools as registered openclaw plugin tools

**The pivot:** stop being an MCP server. Be a registered openclaw plugin,
like Telegram and Slack are.

### Shape

1. `jarvis-openclaw-plugin` is a TypeScript openclaw plugin. Instead of
   registering a `before_tool_call` hook, it registers four tools via the
   factory mechanism:

   - `jarvis__get_schema`
   - `jarvis__get_doc`
   - `jarvis__get_list`
   - `jarvis__run_report`

2. Each tool's factory receives an `OpenClawPluginToolContext`. From it the
   tool reads:

   - `ctx.sessionKey` — always populated, gateway-initiated and
     channel-initiated alike (per `openclaw/src/plugins/tool-types.ts:25`)
   - `ctx.requesterSenderId` — populated for channel-initiated; available for
     future per-user routing in multi-tenant channel deployments

3. The tool's execute function makes an HTTPS POST to Frappe's existing
   `jarvis.api.call_tool` endpoint (built in Phase 1), passing:

   - the tool name (`get_schema`, etc.)
   - the args from the LLM
   - the resolved user identity (via the same sessionKey → user lookup the
     earlier B1 plumbing already supports, calling
     `jarvis.api.lookup_user_by_session`)

4. Frappe receives the call, resolves the user, calls
   `frappe.set_user(user)`, dispatches the tool, returns the result.

### Why this works

- The factory path is openclaw's designed contract for plugins. We get full
  session context. No upstream openclaw change required.
- The Frappe-side surface (`jarvis.api.call_tool`) already exists from Phase 1.
- We delete `jarvis.mcp.serve` — no MCP server, no JSON-RPC envelope, no MCP
  protocol-version handshake. Simpler.
- The `Jarvis Chat Session` DocType + `lookup_user_by_session` endpoint built
  for the B1 attempt are reused as-is — they already solve the
  sessionKey → user mapping.
- Per-tool typed Zod / Typebox schemas instead of opaque MCP params. Better
  LLM tool descriptions, better validation.

### What gets reused vs. removed

| Built earlier | Status under Path A |
|---|---|
| `Jarvis Chat Session` DocType | **Kept.** sessionKey → user mapping is still the source of truth. |
| `jarvis.api.lookup_user_by_session` endpoint | **Kept.** Used by the plugin tool factories. |
| `jarvis-openclaw-plugin` repo + plugin SDK scaffolding | **Kept.** Same plugin, different registration shape. |
| Plugin env vars in `openclaw_bootstrap._write_env_file` | **Kept.** Plugin still needs Frappe URL + token. |
| `jarvis.mcp.serve` (MCP JSON-RPC server) | **Removed.** Path A doesn't need it. |
| `before_tool_call` hook in plugin | **Removed/replaced.** Replaced by tool factories. |
| `_user` param convention in MCP requests | **Removed.** Identity is in the plugin's HTTPS call to Frappe, not the LLM-visible params. |
| `mcp.servers.jarvis` in `openclaw.json` | **Removed.** Replaced by an active plugin entry. |
| Demo's session lookup logic | **Kept.** Same lookup, same DocType, same endpoint. |

### Security properties

Equivalent to or better than what the hook-based design promised:

- Identity comes from the openclaw runtime (`ctx.sessionKey`), populated by
  openclaw itself when the session is created — it cannot be forged by the
  LLM or by tool args.
- The LLM never sees `_user` because it's not a tool param — it's an
  out-of-band HTTPS header from the plugin to Frappe.
- The shared `X-Jarvis-Token` still authenticates the plugin's HTTPS calls.
- `Jarvis Chat Session` rows are still inserted server-side by Python with
  the authenticated initiator, not by anything the LLM can influence.

---

## Trade-offs vs. the original MCP design

| Aspect | MCP server | Path A (registered plugin) |
|---|---|---|
| Protocol surface | Standard MCP — Jarvis could be consumed by any MCP-capable client (Claude Desktop, Cursor, other agent frameworks) | openclaw-specific. Other clients can't consume Jarvis tools without writing their own openclaw plugin. |
| Identity propagation | Blocked by openclaw architecture | Works today |
| Adding a tool | Add Python function + register in Python registry; plugin proxies it automatically | Add Python function AND a TypeScript factory + schema in the plugin |
| LLM tool schema fidelity | Whatever the MCP server emits via `tools/list` | Hand-curated schemas with full openclaw tool-descriptor metadata (categories, danger flags, etc.) |
| "Jarvis works in Claude Desktop" use case | Trivially supported | Would need to re-introduce the MCP server as an additional surface |

The MCP-portability story is the biggest thing we give up. Right now Jarvis's
only consumer is openclaw, so this is a future concern — and if/when it
materializes we can re-add `jarvis.mcp.serve` as a *separate* surface
alongside the openclaw plugin. The two would share the same Python tool
layer.

---

## What would unlock the MCP path in the future

The cleanest upstream fix would be a small openclaw change at
`pi-tool-definition-adapter.ts:241` to pass `ctx: hookContext` to
`runBeforeToolCallHook`, mirroring the line-346 call site. The hook context
data is already in scope; only the wiring is missing. Such a change would let
external MCP servers participate in the same identity-propagation flow that
registered plugin tools enjoy today.

This is worth a future upstream PR. It is not on Jarvis's critical path;
Path A ships identity propagation now without any openclaw-internal change.

---

## References inside this repo

- `jarvis/docs/architecture.md` — the live architecture doc (kept in sync
  with this decision)
- `jarvis/docs/tools-api.md` — `call_tool`'s two auth modes (standard Frappe
  auth + plugin-auth)
- `jarvis/api.py` — `call_tool` plugin-auth path; `lookup_user_by_session`
  endpoint
- `jarvis/jarvis/doctype/jarvis_chat_session/` — sessionKey → user DocType
- `jarvis/openclaw_templates/openclaw.json.j2` — Path A config shape (plugin
  entry, no `mcp` block)
- `jarvis/openclaw_bootstrap.py` — `_install_plugin`, `_write_env_file`

## References outside this repo

- `github.com/Aerele-RnD/jarvis-openclaw-plugin` — the TypeScript plugin
  (`src/index.ts` registers the four tools; `src/session-user.ts` does the
  sessionKey lookup; `src/frappe-client.ts` POSTs to `call_tool`)
- openclaw source (`openclaw/src/plugins/tool-types.ts`,
  `openclaw/src/agents/pi-tool-definition-adapter.ts:241/346`) — for the
  upstream contracts referenced above
