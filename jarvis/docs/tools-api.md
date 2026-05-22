# Tools & API

Jarvis exposes ERPNext data to its agent runtime through a small, permission-aware tool layer. The same surface is available two ways: as Python functions (used internally), and as a whitelisted HTTP endpoint (`call_tool`) used both by external integrations and — in production — by `jarvis-openclaw-plugin` when the agent invokes a `jarvis__*` tool.

Every tool inherits the calling user's ERPNext permissions. The agent can never see DocTypes or records the user themselves can't see. There are **11 tools**: 5 read-only and 6 MUTATING (write). The registry (`list_tools()`) is the source of truth:
`['amend_doc', 'cancel_doc', 'create_doc', 'delete_doc', 'get_doc', 'get_list', 'get_schema', 'run_query', 'run_report', 'submit_doc', 'update_doc']`.

## Read tools

### `get_schema(doctype: str) -> dict`

Module: `jarvis.tools.get_schema`

Returns a DocType's field list with Table fields expanded inline.

```python
from jarvis.tools.get_schema import get_schema
result = get_schema(doctype="Sales Invoice")
# {
#   "doctype": "Sales Invoice",
#   "fields": [
#     {"fieldname": "customer", "fieldtype": "Link", "label": "Customer", "options": "Customer", "reqd": True},
#     ...
#     {"fieldname": "items", "fieldtype": "Table", "label": "Items", "options": "Sales Invoice Item",
#      "reqd": False,
#      "child_fields": [
#         {"fieldname": "item_code", ...},
#         {"fieldname": "qty", ...},
#         ...
#      ]},
#     ...
#   ]
# }
```

| Aspect | Detail |
|---|---|
| Permission check | `frappe.has_permission(doctype, ptype="read")` |
| Raises | `InvalidArgumentError` (empty `doctype` or unknown DocType), `PermissionDeniedError` (calling user lacks read) |
| Child tables | `Table` and `Table MultiSelect` fields carry a `child_fields` list with the linked child DocType's schema. Frappe doesn't allow nested tables, so expansion depth is bounded at 1. Child DocTypes are treated as part of the parent and aren't permission-checked separately. |

### `get_doc(doctype: str, name: str) -> dict`

Module: `jarvis.tools.get_doc`

Returns a single document as a dict, including default fields like `creation`, `owner`.

```python
from jarvis.tools.get_doc import get_doc
result = get_doc(doctype="Customer", name="Acme Corp")
# {"name": "Acme Corp", "customer_name": "Acme Corp", ...}
```

| Aspect | Detail |
|---|---|
| Permission check | `frappe.has_permission(doctype, ptype="read", doc=name)` — record-level, not just DocType-level |
| Raises | `InvalidArgumentError` (empty `doctype` / empty `name` / unknown document), `PermissionDeniedError` (no read on this specific record) |

### `get_list(doctype, fields, filters, order_by, limit) -> list[dict]`

Module: `jarvis.tools.get_list`

```python
from jarvis.tools.get_list import get_list
rows = get_list(
    doctype="Sales Invoice",
    fields=["name", "customer", "grand_total"],
    filters={"status": "Paid", "posting_date": [">", "2026-01-01"]},
    order_by="grand_total desc",
    limit=20,
)
```

| Aspect | Detail |
|---|---|
| Defaults | `fields=["name"]`, `filters={}`, `order_by=None`, `limit=20` |
| Permission check | DocType-level `has_permission(doctype, "read")` PLUS Frappe's per-row filter inside `get_list` (rows the user can't see are silently dropped) |
| Limit cap | `MAX_LIMIT = 1000`. Higher requests raise `InvalidArgumentError`. |
| Raises | `InvalidArgumentError` (empty `doctype`, `limit ≤ 0` or `> 1000`), `PermissionDeniedError` (no read on DocType) |

### `run_report(report_name: str, filters: dict | None) -> dict`

Module: `jarvis.tools.run_report`

Executes a saved Frappe Report by name (Report Builder / Query Report / Script Report).

```python
from jarvis.tools.run_report import run_report
result = run_report(
    report_name="Sales Register",
    filters={"from_date": "2026-01-01", "to_date": "2026-03-31", "company": "Aerele Inc"},
)
# {"columns": [...], "result": [...]}
```

| Aspect | Detail |
|---|---|
| Permission check | Delegated to `frappe.desk.query_report.run`. `frappe.PermissionError` from Frappe is translated to `PermissionDeniedError` so all tools share one exception contract. |
| Raises | `InvalidArgumentError` (empty `report_name` or unknown Report), `PermissionDeniedError` (no permission on the underlying Report) |

### `run_query(query: str, limit: int = 100) -> dict`

Module: `jarvis.tools.run_query`

Executes a read-only `SELECT` against Frappe DocType tables (`tab<DocType>`).
Intended for queries `get_list` can't express: joins across DocTypes,
aggregations (`SUM`, `COUNT`, `AVG`), `GROUP BY`, complex analytics.

```python
from jarvis.tools.run_query import run_query
result = run_query(
    query="""
        SELECT sii.item_code,
               SUM(sii.qty)    AS total_qty,
               SUM(sii.amount) AS total_amt
        FROM `tabSales Invoice Item` sii
        JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE si.docstatus = 1
        GROUP BY sii.item_code
        ORDER BY total_amt DESC
    """,
    limit=50,
)
# {"sql": "...final query with enforced LIMIT...", "rows": [...]}
```

| Aspect | Detail |
|---|---|
| Allowed | Single `SELECT` statement. Tables must be `tab<DocType>` form (backticks optional). Explicit `AS` aliases on aggregate columns. |
| Disallowed | Multi-statement, comments (`--`, `/* */`, `#`), DML/DDL keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, etc.) — including in subqueries. Non-`tab*` tables (`__Auth`, `information_schema.*`). |
| Permission check | DocType-level `frappe.has_permission(<DocType>, "read")` for every referenced table. |
| **NOT enforced** | User Permissions / record-level share/role filters. Frappe's permission engine has no public hook for arbitrary SQL — prefer `get_list` for record-scoped users. |
| Limit cap | `MAX_LIMIT = 1000`. The tool injects `LIMIT <n>` if missing and clamps an existing `LIMIT` to the cap. |
| Returns | `{"sql": <executed query>, "rows": [...]}` — the executed SQL is included so the model can show the user what ran. |
| Raises | `InvalidArgumentError` (bad SQL / forbidden keyword / non-`tab` table / no tables), `PermissionDeniedError` (no read on referenced DocType) |

## Write tools (MUTATING)

Six tools change data. Each enforces the calling user's Frappe write/submit/
cancel/delete permission, runs the DocType's `validate()` hooks, and refuses
protected fields (`name` where autoname forbids it, `owner`, `creation`,
`modified`, `docstatus`, `parent`, etc.). They are **consequential** — the agent
is instructed to **confirm with the user first** (show the DocType, the values,
and the side effects) before calling. Modules: `jarvis.tools.<name>`.

| Tool | Signature | What it does / refused when |
|---|---|---|
| `update_doc` | `update_doc(doctype, name, values: dict)` | Apply field changes to one record. Refused on protected fields; raises `ValidationError` / `PermissionDeniedError` / `DoesNotExistError`. Returns the saved doc. |
| `create_doc` | `create_doc(doctype, values: dict)` | Insert a new document (DocType-level create permission; `validate()` runs). `name` allowed for prompt-autoname DocTypes. Returns the inserted doc incl. its `name`. |
| `submit_doc` | `submit_doc(doctype, name)` | Submit a Draft (docstatus 0→1). Fires `on_submit` side effects (GL postings, stock moves, payments). Refused if not submittable / already submitted / cancelled / no submit permission. |
| `cancel_doc` | `cancel_doc(doctype, name)` | Cancel a Submitted doc (1→2) — fires `on_cancel` reversal entries. Refused if Draft (use delete) / already cancelled / no cancel permission. |
| `delete_doc` | `delete_doc(doctype, name)` | Delete a record outright (most destructive). Refused if Submitted (cancel first) or referenced elsewhere (`LinkExistsError`). |
| `amend_doc` | `amend_doc(doctype, name)` | Create a new Draft copy of a Cancelled doc (`amended_from`). Then edit via `update_doc` + re-`submit_doc`. |

These are exposed to the agent as `jarvis__update_doc` … `jarvis__amend_doc` by
the plugin, with verbose confirm-first descriptions; the Frappe-side functions
are the same registry entries dispatched via `call_tool`.

## Tool registry & dispatcher

Module: `jarvis.tools.registry`

Central name → callable map. Everything that calls a tool goes through `dispatch()`.

```python
from jarvis.tools.registry import list_tools, dispatch

list_tools()
# ['amend_doc', 'cancel_doc', 'create_doc', 'delete_doc', 'get_doc', 'get_list',
#  'get_schema', 'run_query', 'run_report', 'submit_doc', 'update_doc']

dispatch("get_schema", {"doctype": "Customer"})
# (same as calling get_schema directly)
```

| Function | Behavior |
|---|---|
| `list_tools() -> list[str]` | Sorted list of registered tool names. |
| `dispatch(tool_name, args)` | Validates `tool_name` against the registry, validates `args` is a dict, calls the tool with `**args`. Python `TypeError` from missing required kwargs is translated to `InvalidArgumentError` so the wire-level error contract stays consistent. |
| Raises | `ToolNotFoundError` (unknown tool), `InvalidArgumentError` (args not a dict, or missing/extra kwargs), or whatever the underlying tool raises. |

### Adding a new tool

1. Create `app/jarvis/tools/<tool_name>.py` exporting a single function with the public signature you want.
2. Add a permission check (`frappe.has_permission(...)`) and explicit argument validation that raises typed errors from `jarvis.exceptions`.
3. Register it in `app/jarvis/tools/registry.py` — import the function, add an entry to `_TOOLS`.
4. Add a test module `app/jarvis/tests/test_<tool_name>.py` covering happy path, missing args, unknown target, permission denial.
5. Update `test_registry.py`'s `test_list_tools_contains_all_*` assertion.

## HTTP API: `call_tool`

Module: `jarvis.api`

A single whitelisted Frappe endpoint that exposes the dispatcher over HTTP. As
of Phase 2.2.a (refined 2026-05-18) this is also **the entry point used by
`jarvis-openclaw-plugin`** when openclaw's agent invokes a `jarvis__*` tool.
The plugin authenticates with the gateway token (`X-Jarvis-Token`) and
identifies the conversation via `X-Jarvis-Session`; Frappe resolves the
user from the `Jarvis Chat Session` row itself (see `architecture.md` for
the full Path A v2 identity flow).

```
POST /api/method/jarvis.api.call_tool
Authorization: token <api_key>:<api_secret>
Content-Type: application/json

{
  "tool": "get_schema",
  "args": {"doctype": "Customer"}
}
```

Response envelope, success:
```json
{
  "message": {
    "ok": true,
    "data": { ...whatever the tool returned... }
  }
}
```

Response envelope, error:
```json
{
  "message": {
    "ok": false,
    "error": {
      "code": "InvalidArgumentError",
      "message": "doctype is required"
    }
  }
}
```

The outer `message` wrapper is Frappe's standard `@frappe.whitelist()` return envelope; the inner `{ok, data | error}` is Jarvis's.

### Request shape

| Field | Type | Notes |
|---|---|---|
| `tool` | string | Must match a name in `list_tools()` |
| `args` | dict or JSON-encoded string | HTTP clients can pass `args` as either a dict (when the JSON body parses it natively) or as a JSON string (the endpoint decodes it). Other shapes return `InvalidArgumentError`. |

### Error codes

The `error.code` field is always one of these (the exception's `__name__`):

| Code | Meaning |
|---|---|
| `ToolNotFoundError` | `tool` is not registered |
| `InvalidArgumentError` | Bad args (missing required kwargs, wrong type, unknown DocType, etc.) |
| `PermissionDeniedError` | Calling user lacks permission for the requested operation |
| `JarvisError` | Generic base — would only appear if a tool raised the base class directly (it shouldn't) |

`frappe.PermissionError` (raised by Frappe internals when the calling user fails an auth check inside a tool that doesn't already translate it) is mapped to a `PermissionDeniedError` envelope.

### Authentication

Two supported auth modes:

1. **External clients (Phase 1 + general use):** Frappe's standard auth — the
   calling user's session cookie or `Authorization: token <api_key>:<api_secret>`
   header. The user's permissions are exactly what the tools see.
2. **`jarvis-openclaw-plugin` (Path A v2, 2026-05-18):** two headers —
   `X-Jarvis-Token` (shared gateway secret, validated against the
   `agent_token` field on Jarvis Settings) and `X-Jarvis-Session`
   (openclaw `sessionKey` from `ctx.sessionKey`). `call_tool` validates the
   token, looks up `Jarvis Chat Session` to map session → user, and runs
   `frappe.set_user(user)` for the duration of the dispatch. The LLM never
   sees the session key — it's carried by the plugin's HTTP layer.
   Earlier shape (pre-2026-05-18) also required `X-Jarvis-User`; that header
   is gone, and the `jarvis.api.lookup_user_by_session` endpoint has been
   removed.

### Example: Administrator call

```bash
# Get an API key+secret for Administrator (one-time)
bench --site jarvis.localhost execute frappe.core.doctype.user.user.generate_keys \
  --kwargs '{"user": "Administrator"}'
# Print api_key:
bench --site jarvis.localhost execute frappe.client.get_value \
  --kwargs '{"doctype":"User","filters":{"name":"Administrator"},"fieldname":"api_key"}'

# Then:
curl -X POST http://jarvis.localhost:8000/api/method/jarvis.api.call_tool \
  -H "Authorization: token <api_key>:<api_secret>" \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_schema","args":{"doctype":"Customer"}}'
```

### Example: low-permission user

```bash
curl -X POST http://jarvis.localhost:8000/api/method/jarvis.api.call_tool \
  -H "Authorization: token <employee_api_key>:<employee_api_secret>" \
  -H "Content-Type: application/json" \
  -d '{"tool":"get_doc","args":{"doctype":"Sales Invoice","name":"INV-001"}}'
# {"message": {"ok": false, "error": {"code": "PermissionDeniedError", "message": "..."}}}
```

## Exception vocabulary

Module: `jarvis.exceptions`

All errors raised by Jarvis code extend `JarvisError`. Two families:

### Tool / dispatch errors

| Exception | Raised by | When |
|---|---|---|
| `JarvisError` | Base class | (not raised directly) |
| `ToolNotFoundError` | `registry.dispatch` | Unknown tool name |
| `PermissionDeniedError` | Each tool's permission check | Calling user lacks permission |
| `InvalidArgumentError` | Each tool + `registry.dispatch` | Empty/missing required args, unknown DocType/document, oversized `limit`, etc. |

### Openclaw push errors (Phase 2.1)

These appear in `last_sync_status` on Jarvis Settings when the on_update hook can't successfully push credentials.

| Exception | Raised by | When |
|---|---|---|
| `OpenclawUnreachableError` | `openclaw_push.reload_secrets` | WebSocket connection refused, handshake rejected, container down |
| `OpenclawReloadFailedError` | `openclaw_push.reload_secrets` | Gateway responded `ok: false` to `secrets.reload`, or the exchange timed out (10s) |
| `OpenclawRestartFailedError` | `openclaw_push.restart_gateway`, `openclaw_bootstrap.*` | `docker compose` returned non-zero, or the gateway didn't come back healthy within the timeout |

The HTTP `call_tool` endpoint never raises these — they're only relevant to the credentials update path, where the `on_update` hook catches them and records the failure in `last_sync_status`.
