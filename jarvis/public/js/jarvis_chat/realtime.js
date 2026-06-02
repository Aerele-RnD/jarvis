// Realtime event router. The server publishes to a single `jarvis:event`
// channel; we dispatch by `kind`.

import { state } from "./state.js";
import {
	buildMessageEl,
	updateMessage,
	buildToolGroupEl,
	updateToolGroupCount,
} from "./messages.js";

/**
 * Find the most recent openclaw-side tool row in a group whose tool name
 * matches `<jarvis__>?<bareName>` and which hasn't already had a result
 * attached. Returns a jQuery object (possibly empty).
 *
 * Used by tool:result to merge with the row tool:start already created
 * instead of rendering a duplicate.
 */
function findMatchingOpenclawRow($group, bareToolName) {
	if (!$group || !$group.length || !bareToolName) return $();
	const candidates = $group.find(
		'.jarvis-message-tool:not([data-result-attached="1"])'
	);
	for (let i = candidates.length - 1; i >= 0; i--) {
		const $cand = $(candidates[i]);
		const rowName = $cand.find(".jarvis-tool-name").text().trim();
		const stripped = rowName.replace(/^jarvis__/, "");
		if (stripped === bareToolName) return $cand;
	}
	return $();
}

function ensureCurrentTurnGroup($list) {
	// Find the last turn container; if it has no tool group yet, insert one
	// before the assistant message (so visual order stays user → tools →
	// assistant even when the assistant placeholder DOM-ed in first).
	let $turn = $list.find(".jarvis-turn").last();
	if (!$turn.length) {
		// Realtime event arrived before any turn was rendered - fall back to
		// a top-level group. The next loadConversation() will reorganize.
		$turn = $('<div class="jarvis-turn jarvis-turn-orphan"></div>');
		$list.append($turn);
	}
	let $group = $turn.find(".jarvis-tool-group").last();
	if (!$group.length) {
		$group = buildToolGroupEl();
		const $assistant = $turn.find(".jarvis-message-assistant").last();
		if ($assistant.length) $group.insertBefore($assistant);
		else $turn.append($group);
	}
	return $group;
}

export function attachRealtime({ $list, $thinking, scrollToBottom, loadConversation }) {
	frappe.realtime.on("jarvis:event", (payload) => {
		if (payload.conversation_id !== state.current_conversation) return;

		switch (payload.kind) {
			case "run:start":
				// The assistant placeholder row is created server-side; reload to
				// pick it up. Hide the thinking pill now that the run is underway.
				hideThinking($thinking);
				loadConversation(state.current_conversation, { keepWelcomeHidden: true });
				return;

			case "assistant:delta": {
				hideThinking($thinking);
				const $el = $list.find(`[data-msg="${payload.message_id}"]`);
				if (!$el.length) return;
				updateMessage($el, {
					name: payload.message_id,
					role: "assistant",
					content: payload.text,
					streaming: true,
				});
				scrollToBottom();
				return;
			}

			case "tool:start": {
				hideThinking($thinking);
				const $existing = $list.find(`[data-msg="${payload.message_id}"]`);
				if (!$existing.length) {
					const $group = ensureCurrentTurnGroup($list);
					$group.find(".jarvis-tool-group-body").append(
						buildMessageEl({
							name: payload.message_id,
							role: "tool",
							tool_name: payload.tool_name,
							tool_status: "running",
						})
					);
					updateToolGroupCount($group);
				}
				scrollToBottom();
				return;
			}

			case "tool:end": {
				const $el = $list.find(`[data-msg="${payload.message_id}"]`);
				if ($el.length) {
					updateMessage($el, {
						name: payload.message_id,
						role: "tool",
						tool_name: payload.tool_name,
						tool_status: payload.status || "completed",
					});
					updateToolGroupCount($el.closest(".jarvis-tool-group"));
				}
				return;
			}

			case "tool:result": {
				// Two event streams fire per tool call:
				//   - openclaw tool:start/end carry the prefixed name
				//     (`jarvis__get_list`) but no result data
				//   - Frappe call_tool tool:result carries the bare name
				//     (`get_list`) + args + result
				// Merge them into a single row so we don't double-render.
				let $el = $list.find(`[data-msg="${payload.tool_message_id}"]`);
				if (!$el.length) {
					$el = findMatchingOpenclawRow(
						ensureCurrentTurnGroup($list),
						payload.tool_name,
					);
				}
				if ($el && $el.length) {
					updateMessage($el, {
						name: payload.tool_message_id,
						role: "tool",
						tool_name: payload.tool_name,
						tool_status: payload.status,
						tool_result: payload.result,
					});
					$el.attr("data-result-attached", "1");
					$el.attr("data-msg", payload.tool_message_id);
					updateToolGroupCount($el.closest(".jarvis-tool-group"));
				} else {
					// No matching openclaw row - first-render path (e.g.
					// call_tool dispatched outside an openclaw turn).
					const $group = ensureCurrentTurnGroup($list);
					$group.find(".jarvis-tool-group-body").append(
						buildMessageEl({
							name: payload.tool_message_id,
							role: "tool",
							tool_name: payload.tool_name,
							tool_status: payload.status,
							tool_result: payload.result,
						})
					);
					updateToolGroupCount($group);
					scrollToBottom();
				}
				return;
			}

			case "run:end": {
				const $el = $list.find(`[data-msg="${payload.message_id}"]`);
				if ($el.length) $el.find(".jarvis-cursor").remove();
				return;
			}

			case "run:error":
				hideThinking($thinking);
				frappe.show_alert({
					message: `Run error: ${payload.error || "unknown"}`,
					indicator: "red",
				});
				return;
		}
	});
}

export function showThinking($thinking) {
	state.thinking_timer = setTimeout(() => {
		$thinking.prop("hidden", false);
	}, 150);
}

export function hideThinking($thinking) {
	if (state.thinking_timer) {
		clearTimeout(state.thinking_timer);
		state.thinking_timer = null;
	}
	$thinking.prop("hidden", true);
}
