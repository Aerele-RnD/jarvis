// Rendering helpers for individual chat messages. Stateless on purpose —
// they receive a message dict and return a DOM element. The realtime layer
// patches existing elements via updateMessage().

export function renderMarkdown(text) {
	const prepped = autoTablify(text || "");
	if (typeof frappe.markdown === "function") {
		try {
			return frappe.markdown(prepped);
		} catch (_) {
			// fall through to plain rendering
		}
	}
	const escaped = frappe.utils.escape_html(prepped);
	return escaped.replace(/\n/g, "<br>");
}

/**
 * Convert whitespace-aligned tables in plain text to GFM markdown pipe
 * tables so Showdown's table extension can render them.
 *
 * LLMs frequently emit tables as space-separated columns despite SOUL.md
 * asking for pipes. This client-side fallback makes the renderer robust
 * against that — every model, every prompt — without depending on the
 * agent to follow instructions.
 *
 * Heuristic: any run of 2+ consecutive non-blank lines where each line
 * has 2+ tokens separated by 2+ spaces (or tabs). Pipe-prefixed lines
 * are left alone. Fenced code blocks are skipped entirely.
 */
function autoTablify(text) {
	if (!text || text.indexOf("\n") < 0) return text;
	const lines = text.split("\n");
	const out = [];
	let inFence = false;
	let i = 0;

	while (i < lines.length) {
		const line = lines[i];

		// Skip everything inside ``` fences.
		if (/^\s*```/.test(line)) {
			inFence = !inFence;
			out.push(line);
			i++;
			continue;
		}
		if (inFence) {
			out.push(line);
			i++;
			continue;
		}

		if (looksLikeTableRow(line)) {
			const block = [];
			let j = i;
			while (j < lines.length && looksLikeTableRow(lines[j])) {
				block.push(splitColumns(lines[j]));
				j++;
			}
			if (block.length >= 2) {
				const maxCols = Math.max(...block.map((r) => r.length));
				out.push("| " + padRow(block[0], maxCols).join(" | ") + " |");
				out.push("|" + " --- |".repeat(maxCols));
				for (let k = 1; k < block.length; k++) {
					out.push("| " + padRow(block[k], maxCols).join(" | ") + " |");
				}
				i = j;
				continue;
			}
		}

		out.push(line);
		i++;
	}
	return out.join("\n");
}

function looksLikeTableRow(line) {
	if (!line || !line.trim()) return false;
	// Already pipe-formatted — let Showdown handle it directly.
	if (/^\s*\|/.test(line)) return false;
	// Skip markdown structures that might have multi-space gaps for
	// stylistic reasons but aren't actually tables.
	if (/^\s*[-*+]\s/.test(line)) return false;     // bullet list item
	if (/^\s*\d+\.\s/.test(line)) return false;     // numbered list item
	if (/^\s*#{1,6}\s/.test(line)) return false;    // heading
	if (/^\s*>\s/.test(line)) return false;         // blockquote
	// Need 2+ columns when split on runs of multi-space / tab.
	return splitColumns(line).length >= 2;
}

function splitColumns(line) {
	return line
		.split(/\s{2,}|\t+/)
		.map((s) => s.trim())
		.filter((s) => s !== "");
}

function padRow(cols, n) {
	const padded = cols.slice();
	while (padded.length < n) padded.push("");
	return padded;
}

export function buildMessageEl(msg) {
	const $m = $(
		`<div class="jarvis-message jarvis-message-${msg.role}" data-msg="${msg.name}"></div>`
	);
	if (msg.creation) $m.attr("data-creation", msg.creation);
	updateMessage($m, msg);
	return $m;
}

export function updateMessage($el, msg) {
	// Persist the creation timestamp on the element so subsequent realtime
	// updates (which carry no `creation` field) can still render it.
	if (msg.creation && !$el.attr("data-creation")) {
		$el.attr("data-creation", msg.creation);
	}

	if (msg.role === "tool") {
		$el.html(renderToolBody(msg));
		bindToolToggles($el);
	} else if (msg.role === "assistant") {
		const html = renderMarkdown(msg.content || "");
		const errorBlock = msg.error ? renderAssistantError(msg) : "";
		const cursor = msg.streaming
			? '<span class="jarvis-cursor"></span>'
			: "";
		const bubbleClass = msg.error
			? "jarvis-bubble jarvis-bubble-errored"
			: "jarvis-bubble";
		$el.html(`
			<div class="${bubbleClass}">
				${html}${cursor}${errorBlock}
			</div>
			${timestampHtml($el, msg)}
		`);
	} else {
		$el.html(`
			<div class="jarvis-bubble">${frappe.utils.escape_html(msg.content || "")}</div>
			${timestampHtml($el, msg)}
		`);
	}
}

// ---- Errored assistant turn ------------------------------------------
//
// When an agent run fails (rate limit, transport error, etc.) the worker
// marks the assistant message with `error` and stops streaming. We render
// an inline error block with the failure reason, a relative timestamp
// (auto-refreshing via frappe-timestamp), and a Retry button bound to
// the message id so the click handler in index.js can re-enqueue the
// worker for the preceding user turn.

function renderAssistantError(msg) {
	const errored = msg.creation
		? frappe.datetime.comment_when(msg.creation)
		: "just now";
	return `
		<div class="jarvis-error-block">
			<div class="jarvis-error-row">
				<span class="jarvis-error-icon">⚠</span>
				<span class="jarvis-error-text">${frappe.utils.escape_html(msg.error)}</span>
			</div>
			<div class="jarvis-error-foot">
				<span class="jarvis-error-when">Failed ${errored}</span>
				<button class="btn btn-xs btn-default jarvis-retry-btn"
				        data-msg="${frappe.utils.escape_html(msg.name)}">
					Retry
				</button>
			</div>
		</div>
	`;
}

function timestampHtml($el, msg) {
	// Read from the data attribute first (set by buildMessageEl on initial
	// render from the DB-backed conversation). Realtime delta payloads don't
	// carry a creation field — fall back to "just now" so the assistant
	// bubble has a meaningful stamp while streaming.
	const creation = $el.attr("data-creation");
	if (!creation) {
		return msg.streaming
			? '<div class="jarvis-msg-time">just now</div>'
			: "";
	}
	// frappe.datetime.comment_when returns an HTML span that auto-refreshes
	// (e.g. "just now" → "1 min ago"); the title attribute holds the
	// absolute timestamp for hover.
	const rendered = frappe.datetime.comment_when(creation);
	return `<div class="jarvis-msg-time">${rendered}</div>`;
}

function renderToolBody(msg) {
	const status = msg.tool_status || "running";
	const statusBadge = `<span class="jarvis-tool-status jarvis-tool-${status}">${status}</span>`;
	const icon = status === "running"
		? '<span class="jarvis-tool-icon jarvis-spin">⟳</span>'
		: status === "error"
			? '<span class="jarvis-tool-icon">⚠</span>'
			: '<span class="jarvis-tool-icon">✓</span>';

	let body = "";
	if (msg.tool_result) {
		body = renderToolResultBody(msg.tool_result);
	}

	return `
		<div class="jarvis-tool-head">
			${icon}
			<span class="jarvis-tool-name">${frappe.utils.escape_html(msg.tool_name || "")}</span>
			${statusBadge}
		</div>
		${body}
	`;
}

// ---- Tool result rendering -------------------------------------------
//
// Tool results come back in several shapes:
//   - call_tool envelope:  {ok: true, data: ...}
//   - run_query envelope:  {sql: "...", rows: [...]}
//   - get_schema envelope: {doctype, fields: [...]}
//   - get_list envelope:   data is a bare array
// When we can find a row array, render it as an HTML table — drastically
// more readable than the equivalent JSON for an LLM-driven UI. Fall back
// to <pre> JSON for unstructured shapes.

function renderToolResultBody(toolResult) {
	let parsed = toolResult;
	if (typeof parsed === "string") {
		try { parsed = JSON.parse(parsed); } catch (_) { /* keep as string */ }
	}

	const table = extractTable(parsed);
	const rawText = typeof parsed === "string"
		? parsed
		: JSON.stringify(parsed, null, 2);

	if (table) {
		const rowCount = table.rows.length;
		const label = `${rowCount} ${rowCount === 1 ? "row" : "rows"}`;
		return `
			<details class="jarvis-tool-details" open>
				<summary>${label}</summary>
				${renderTable(table)}
				<details class="jarvis-tool-raw">
					<summary>Raw JSON</summary>
					<pre>${frappe.utils.escape_html(rawText)}</pre>
				</details>
			</details>
		`;
	}

	const collapsed = rawText.length > 400;
	return `
		<details class="jarvis-tool-details" ${collapsed ? "" : "open"}>
			<summary>${collapsed ? "Show result" : "Result"}</summary>
			<pre>${frappe.utils.escape_html(rawText)}</pre>
		</details>
	`;
}

/**
 * Find the most likely row array inside a tool result. Returns
 * `{ keys: string[], rows: object[] }` when the data looks tabular,
 * `null` otherwise.
 */
function extractTable(result) {
	if (result == null) return null;

	// Unwrap call_tool envelope first.
	if (typeof result === "object" && result.ok === true && result.data !== undefined) {
		return extractTable(result.data);
	}

	// Direct array — most get_list responses.
	if (Array.isArray(result)) return tablify(result);

	if (typeof result === "object") {
		// run_query: {sql, rows: [...]}
		if (Array.isArray(result.rows)) return tablify(result.rows);
		// get_schema: {doctype, fields: [...]}
		if (Array.isArray(result.fields)) return tablify(result.fields);
		// Frappe Report shape: {columns: [...], result: [...]}
		if (Array.isArray(result.result)) return tablify(result.result);
		// Single record (e.g. get_doc) — render the doc's fields as a
		// 2-column key/value table.
		return tablifyObject(result);
	}
	return null;
}

/**
 * Render a single plain object as `{keys: ["field", "value"], rows: [...]}`
 * so the existing renderTable can produce a 2-column key/value view. Used
 * for get_doc results where the agent fetched a single record.
 *
 * `name` is hoisted to the top if present — for Frappe docs it's the
 * primary key and almost always the first thing a reader wants to see.
 */
function tablifyObject(obj) {
	if (!obj || typeof obj !== "object" || Array.isArray(obj)) return null;
	const entries = Object.entries(obj);
	if (entries.length === 0) return null;
	const ordered = entries.slice();
	const nameIdx = ordered.findIndex(([k]) => k === "name");
	if (nameIdx > 0) {
		const [nameEntry] = ordered.splice(nameIdx, 1);
		ordered.unshift(nameEntry);
	}
	return {
		keys: ["field", "value"],
		rows: ordered.map(([k, v]) => ({ field: k, value: v })),
	};
}

function tablify(rows) {
	if (!Array.isArray(rows) || rows.length === 0) return null;
	// Every row must be a plain object (not array, not primitive).
	const allPlain = rows.every(
		(r) => r != null && typeof r === "object" && !Array.isArray(r),
	);
	if (!allPlain) return null;

	// Union of keys in first-seen order so column layout matches the
	// natural order the tool returned (preserves "name first" etc).
	const keys = [];
	const seen = new Set();
	for (const row of rows) {
		for (const k of Object.keys(row)) {
			if (!seen.has(k)) {
				seen.add(k);
				keys.push(k);
			}
		}
	}
	if (keys.length === 0) return null;
	return { keys, rows };
}

function renderTable({ keys, rows }) {
	const head = keys
		.map((k) => `<th>${frappe.utils.escape_html(k)}</th>`)
		.join("");
	const body = rows
		.map((row) => {
			const cells = keys.map((k) => {
				const v = row[k];
				let cell;
				if (v === null || v === undefined) {
					cell = '<span class="jarvis-tool-null">—</span>';
				} else if (typeof v === "object") {
					// Nested objects/arrays don't fit a flat table; show their
					// JSON in the cell with a tooltip for the full value.
					const json = JSON.stringify(v);
					const display = json.length > 60 ? json.slice(0, 57) + "…" : json;
					cell = `<span title="${frappe.utils.escape_html(json)}">${frappe.utils.escape_html(display)}</span>`;
				} else {
					cell = frappe.utils.escape_html(String(v));
				}
				return `<td>${cell}</td>`;
			}).join("");
			return `<tr>${cells}</tr>`;
		})
		.join("");
	return `
		<div class="jarvis-tool-table-wrap">
			<table class="jarvis-tool-table">
				<thead><tr>${head}</tr></thead>
				<tbody>${body}</tbody>
			</table>
		</div>
	`;
}

function bindToolToggles($el) {
	// Native <details> handles its own toggling; nothing to do for now.
	// Hook left here so future affordances (copy button, etc.) have a home.
	void $el;
}

// ---- Agent loop (tool group) -----------------------------------------
//
// Group renderer: consecutive tool messages within a turn collapse into a
// single <details> block so the conversation reads
//   user → [collapsable agent trace] → assistant
// instead of a wall of tool bubbles between turns.

export function buildToolGroupEl() {
	const $g = $(`
		<details class="jarvis-tool-group" open>
			<summary class="jarvis-tool-group-summary">
				<span class="jarvis-tool-group-chevron">▸</span>
				<span class="jarvis-tool-group-label">Agent loop</span>
				<span class="jarvis-tool-group-count"></span>
				<span class="jarvis-tool-group-status"></span>
			</summary>
			<div class="jarvis-tool-group-body"></div>
		</details>
	`);
	return $g;
}

export function updateToolGroupCount($group) {
	const $tools = $group.find(".jarvis-message-tool");
	const count = $tools.length;
	$group
		.find(".jarvis-tool-group-count")
		.text(count ? `· ${count} ${count === 1 ? "tool" : "tools"}` : "");

	// Roll up status: running > error > completed
	let status = "completed";
	if ($tools.find(".jarvis-tool-running").length) status = "running";
	else if ($tools.find(".jarvis-tool-error").length) status = "error";

	const $st = $group.find(".jarvis-tool-group-status");
	$st.removeClass(
		"jarvis-tool-running jarvis-tool-completed jarvis-tool-error"
	);
	$st.addClass(`jarvis-tool-${status}`).text(status);
}
