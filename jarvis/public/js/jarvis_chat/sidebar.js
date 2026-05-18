// Sidebar rendering and conversation-list logic.

import * as api from "./api.js";
import { state } from "./state.js";

export async function refreshSidebar($sidebar, $empty, onSelect, _onArchive) {
	// Note: archive action intentionally not surfaced per-row. Conversations
	// are durable from the sidebar; archive is reserved for a future menu so
	// rows can't be removed by an accidental icon click.
	const rows = await api.listConversations();
	state.conversations = rows;
	$sidebar.empty();

	if (!rows.length) {
		$empty.prop("hidden", false);
		return;
	}
	$empty.prop("hidden", true);

	rows.forEach((c) => {
		const isEmpty = (c.message_count || 0) === 0;
		const title = c.title || (isEmpty ? "New chat" : "(untitled)");
		const when = c.last_active_at
			? frappe.datetime.comment_when(c.last_active_at)
			: "";

		const $item = $(`
			<div class="jarvis-conv-item" data-name="${c.name}">
				<div class="jarvis-conv-main">
					<div class="jarvis-conv-title">${frappe.utils.escape_html(title)}</div>
					<div class="jarvis-conv-meta">${when}${
						isEmpty ? ' <span class="jarvis-empty-tag">empty</span>' : ""
					}</div>
				</div>
			</div>
		`);

		if (c.name === state.current_conversation) $item.addClass("active");

		$item.on("click", () => onSelect(c.name));

		$sidebar.append($item);
	});
}

export function findEmptyConversation() {
	return state.conversations.find((c) => (c.message_count || 0) === 0);
}
