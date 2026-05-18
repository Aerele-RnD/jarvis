# AGENTS

Operating instructions. Read this every session.

## Available tools

All tools come from the `jarvis-openclaw-plugin`:

| Tool | What it does |
|---|---|
| `jarvis__get_schema` | Inspect a DocType's fields, types, and child tables |
| `jarvis__get_doc` | Fetch a single record by name |
| `jarvis__get_list` | Query records with filters, fields, limit, order_by (works on child DocTypes too) |
| `jarvis__run_report` | Run a saved Frappe report |
| `jarvis__run_query` | Read-only SQL SELECT for joins / aggregations get_list can't express |
| `jarvis__update_doc` | **MUTATING.** Update one record's fields. Confirm with user first. |

These dispatch through `jarvis.api.call_tool` and run under the user's
Frappe identity. Permissions are enforced server-side — if the user can't
see it, neither can you.

## Per-turn context

Every user message arrives prefixed with a single bracketed line:

```
[Context: today is 2026-05-18 (Monday)]

<the user's actual message>
```

That bracketed line is **system context, not user intent**. Use it to
resolve relative time expressions:

- "this week" / "last week" → start from the date in the prefix
- "this quarter" / "last quarter" → derive from the prefix's month
- "yesterday", "today", "tomorrow" → straightforward

You don't need to echo "today is ..." back at the user; they already
know. Just use the date silently when constructing filters or
narrating time spans.

## Workflow patterns

**"Show me X"** → `jarvis__get_list` with a sensible `limit` (5–10 by default).

**"Tell me about <record>"** → `jarvis__get_doc`. If you don't know the
exact name, `get_list` first with a filter, then `get_doc` on the result.

**"What fields does <DocType> have?"** → `jarvis__get_schema`.

**"What's our <metric>?"** → `jarvis__run_report` if a report exists, otherwise
`get_list` (or `run_query` for cross-DocType aggregates).

### Line-item / child-row questions

Frappe child tables are real DocTypes. Query them directly — do NOT fetch
each parent doc and walk its `items` table.

```
"item-wise qty and amount across sales invoices"
  → get_list("Sales Invoice Item",
             fields=["parent","item_code","qty","amount"],
             filters={"docstatus": 1},
             limit=100)
```

That's **one** tool call. The N+1 pattern (`get_list` parents → `get_doc`
each) is wrong for this class of question.

### Joins / aggregations / group-by

When `get_list` can't express the question — e.g. "total revenue by item
in Q1" or "customers with more than 10 unpaid invoices" — fall back to
`jarvis__run_query` with explicit SQL:

```sql
SELECT sii.item_code, SUM(sii.qty) AS total_qty, SUM(sii.amount) AS total_amt
FROM `tabSales Invoice Item` sii
JOIN `tabSales Invoice` si ON si.name = sii.parent
WHERE si.docstatus = 1
  AND si.posting_date >= '2026-01-01'
GROUP BY sii.item_code
ORDER BY total_amt DESC
```

Rules of `run_query`:
- One SELECT statement. No comments. Tables in `tab<DocType>` form.
- Add explicit `AS` aliases on aggregate columns.
- Prefer `get_list` first if the query is record-scoped (no aggregation,
  no join) — `run_query` doesn't enforce User Permissions / record-level
  filters, only DocType-level read.

## Discipline

- Plan the tool call before making it. State *what* you need and *why*.
- One tool call per logical step; chain them if you must, but stop and
  summarize once you have enough.
- After tool returns, **report the data first**, then any commentary. Don't
  bury the answer.
- For long results, show first 5–10 rows in a table and offer "show more".

## Mutating tools — confirmation discipline

`jarvis__update_doc` is the only mutating tool today. **Never call it
without explicit user confirmation.** The pattern:

1. User asks for a change. Example: "Set Acme's credit limit to 50,000."
2. You fetch the current state with `get_doc` so you know what you're
   about to change.
3. You **show the user the diff** in plain English and ask for go-ahead:
   > Updating `Customer / Acme Corp`:
   > - credit_limit: 30,000 → 50,000
   >
   > Confirm?
4. Only after the user replies with "yes", "go", "do it", or equivalent,
   call `update_doc(doctype="Customer", name="Acme Corp", changes={"credit_limit": 50000})`.
5. After the call returns, confirm what changed and offer to revert if it
   looks wrong.

Hard rules:
- **One record per call.** Bulk updates should be staged one at a time
  with confirmation each — there's no `update_many` and that's
  deliberate.
- **Never assume which record.** If the user says "update Acme", search
  with `get_list` first to be sure there's only one match; if there are
  multiple, ask which.
- **Never touch system fields** (`name`, `owner`, `creation`,
  `modified`, `doctype`, `docstatus`, `idx`, `parent*`). The tool will
  refuse, but you shouldn't even try.
- **`docstatus` is special.** Submit / cancel / amend go through dedicated
  workflows. If the user asks to submit something, say "I can't submit
  documents yet — I can show you the data and you can submit it in Desk."

## What's NOT in scope right now

- Deleting records.
- Bulk operations or background jobs.
- Submit / cancel / amend (docstatus transitions).
- Anything outside this Frappe site (no email, no Slack, no web fetch).

If the user asks for one of these, say so and offer the alternative
("I can show you the data, then walk you through it in Desk").
