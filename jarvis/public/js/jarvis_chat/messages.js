// Rendering helpers for individual chat messages. Stateless on purpose —
// they receive a message dict and return a DOM element. The realtime layer
// patches existing elements via updateMessage().

export function renderMarkdown(text) {
	if (typeof frappe.markdown === "function") {
		try {
			return frappe.markdown(text || "");
		} catch (_) {
			// fall through to plain rendering
		}
	}
	const escaped = frappe.utils.escape_html(text || "");
	return escaped.replace(/\n/g, "<br>");
}

export function buildMessageEl(msg) {
	const $m = $(
		`<div class="jarvis-message jarvis-message-${msg.role}" data-msg="${msg.name}"></div>`
	);
	updateMessage($m, msg);
	return $m;
}

export function updateMessage($el, msg) {
	if (msg.role === "tool") {
		$el.html(renderToolBody(msg));
		bindToolToggles($el);
	} else if (msg.role === "assistant") {
		const html = renderMarkdown(msg.content || "");
		$el.html(`
			<div class="jarvis-bubble">
				${html}${msg.streaming ? '<span class="jarvis-cursor"></span>' : ""}
			</div>
		`);
	} else {
		$el.html(`
			<div class="jarvis-bubble">${frappe.utils.escape_html(msg.content || "")}</div>
		`);
	}
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
		const text =
			typeof msg.tool_result === "string"
				? msg.tool_result
				: JSON.stringify(msg.tool_result, null, 2);
		const collapsed = text.length > 400;
		body = `
			<details class="jarvis-tool-details" ${collapsed ? "" : "open"}>
				<summary>${collapsed ? "Show result" : "Result"}</summary>
				<pre>${frappe.utils.escape_html(text)}</pre>
			</details>
		`;
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
