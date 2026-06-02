// Sidebar rendering and conversation-list logic.

import * as api from "./api.js";
import { state } from "./state.js";

// Trash-can SVG (same stroke style as other icons in the page).
const TRASH_ICON = `
	<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
	     stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
		<polyline points="3 6 5 6 21 6"></polyline>
		<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path>
		<path d="M10 11v6"></path>
		<path d="M14 11v6"></path>
		<path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"></path>
	</svg>`;

export async function refreshSidebar($sidebar, $empty, onSelect, onArchive) {
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
				<button type="button" class="jarvis-conv-delete"
				        aria-label="Delete conversation" title="Delete">${TRASH_ICON}</button>
			</div>
		`);

		if (c.name === state.current_conversation) $item.addClass("active");

		$item.on("click", () => onSelect(c.name));

		// Per-row delete (soft-delete via archive — sidebar's list query
		// filters status='Active', so archived rows fall out of view).
		// Delegates the API call + cleanup to onArchive (the controller in
		// index.js) so this stays a pure UI affordance.
		$item.find(".jarvis-conv-delete").on("click", async (e) => {
			e.stopPropagation();   // don't trigger onSelect on the row
			const ok = window.confirm(
				`Delete "${title}"?\n\nThis can't be undone.`
			);
			if (!ok) return;
			try {
				if (typeof onArchive === "function") {
					await onArchive(c.name);
				} else {
					// Fallback if no callback is wired (shouldn't happen).
					await api.archiveConversation(c.name);
				}
				frappe.show_alert({
					message: __("Deleted") + ` "${title}"`,
					indicator: "orange",
				});
			} catch (err) {
				frappe.show_alert({
					message: __("Couldn't delete: ") + (err.message || err),
					indicator: "red",
				});
			}
		});

		$sidebar.append($item);
	});
}

export function findEmptyConversation() {
	return state.conversations.find((c) => (c.message_count || 0) === 0);
}
