// Main controller. Wires the sidebar, message list, input, and realtime
// router together. Exposes `init(wrapper)` for the Desk page loader.

import * as api from "./api.js";
import { state } from "./state.js";
import { PAGE_HTML } from "./template.js";
import { buildMessageEl, buildToolGroupEl, updateToolGroupCount } from "./messages.js";
import { refreshSidebar, findEmptyConversation } from "./sidebar.js";
import { attachRealtime, showThinking, hideThinking } from "./realtime.js";

export function init(wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Jarvis Chat"),
		single_column: true,
	});

	const root = $(page.body).addClass("jarvis-chat-page");
	root.html(PAGE_HTML);

	// Measure the Desk chrome (navbar + page-head + body padding) so we can
	// fill the remaining viewport precisely. Fixed-value subtraction from
	// 100vh leaves the bottom of the layout below the fold and breaks scroll.
	function syncChromeHeight() {
		const rect = root[0].getBoundingClientRect();
		const chrome = Math.max(0, Math.round(rect.top + 16));
		root[0].style.setProperty("--jarvis-chrome-h", chrome + "px");
	}
	syncChromeHeight();
	$(window).on("resize.jarvis-chat", syncChromeHeight);
	root.on("remove", () => $(window).off("resize.jarvis-chat"));

	// Brand the page header so users see this is Jarvis at a glance.
	// Injected into Frappe's .title-area before the title text.
	const $head = $(page.wrapper).find(".page-head .title-area");
	if ($head.length && !$head.find(".jarvis-header-badge").length) {
		$head.prepend(`
			<span class="jarvis-header-badge" title="Jarvis">
				<span class="jarvis-header-badge-mark">✦</span>
				<span class="jarvis-header-badge-name">Jarvis</span>
			</span>
		`);
	}

	// Promote "New Chat" to the page header so the chrome above isn't
	// wasted space. The sidebar still highlights what's open.
	page.set_primary_action(__("+ New Chat"), () => onNewChat());

	const $list = root.find(".jarvis-message-list");
	const $sidebar = root.find(".jarvis-conversation-list");
	const $sidebarEmpty = root.find(".jarvis-sidebar-empty");
	const $input = root.find(".jarvis-input");
	const $send = root.find(".jarvis-send-btn");
	const $sendLabel = $send.find(".jarvis-send-label");
	const $sendSpinner = $send.find(".jarvis-send-spinner");
	const $thinking = root.find(".jarvis-thinking");
	const $welcome = $list.find(".jarvis-welcome");

	// ---- Helpers --------------------------------------------------------

	function scrollToBottom() {
		if ($list[0]) $list.scrollTop($list[0].scrollHeight);
	}

	function setSendingState(sending) {
		state.is_sending = sending;
		$send.prop("disabled", sending || !$input.val().trim());
		$sendLabel.prop("hidden", sending);
		$sendSpinner.prop("hidden", !sending);
		$input.prop("disabled", sending);
		// Lock the header primary action too so a mid-send New-Chat click
		// can't reset state under the worker.
		page.btn_primary?.prop?.("disabled", sending);
	}

	function autoGrowInput() {
		const el = $input[0];
		if (!el) return;
		el.style.height = "auto";
		const max = 160; // ~6 rows
		el.style.height = Math.min(el.scrollHeight, max) + "px";
	}

	function renderWelcome() {
		$list.empty().append($welcome);
		$welcome.show();
		page.set_title(__("Jarvis Chat"));
		syncUrl(null);
		// Welcome screen still shows the picker (oauth mode) so the customer
		// can choose a model for the next conversation. Keep
		// current_model_override in state so the next send_message threads it.
		state.current_conversation = null;
		refreshModelPickerVisibility?.();
		// Reflect the current (possibly preserved) override in the dropdown.
		$modelPicker?.val(state.current_model_override || "");
	}

	// Reflect the active conversation in the URL so refresh / share / back
	// land on the same chat. Uses replaceState - we don't want every sidebar
	// click to push a history entry.
	function syncUrl(name) {
		const target = name ? `/app/jarvis-chat/${encodeURIComponent(name)}` : "/app/jarvis-chat";
		if (window.location.pathname === target) return;
		window.history.replaceState({}, "", target);
	}

	// ---- Model picker ---------------------------------------------------

	const $convToolbar = root.find(".jarvis-conv-toolbar");
	const $modelPicker = root.find(".jarvis-model-picker");

	function rebuildModelPickerOptions() {
		// Source of truth for "what models can the customer pick?" is the
		// SUBSCRIPTION_MODELS map fetched on init. First option is "Default
		// - <settings.llm_model>" which clears the override.
		const allowed = (state.subscription_models || {})[state.llm_provider] || [];
		const defaultLabel =
			__("Default") + " - " + (state.llm_model || "(unset)");
		const opts = [
			`<option value="">${frappe.utils.escape_html(defaultLabel)}</option>`,
			...allowed.map(
				(m) =>
					`<option value="${frappe.utils.escape_html(m)}">${
						frappe.utils.escape_html(m)
					}</option>`,
			),
		];
		$modelPicker.html(opts.join(""));
	}

	function refreshModelPickerVisibility() {
		// Shown in oauth mode (api_key mode has no multi-model picker).
		// Visible on the welcome screen too - the picked value gets applied
		// to whichever conversation receives the first send_message.
		const show = state.llm_auth_mode === "oauth";
		$convToolbar.prop("hidden", !show);
	}

	function syncModelPickerToConversation(model_override) {
		state.current_model_override = model_override || "";
		$modelPicker.val(state.current_model_override);
		refreshModelPickerVisibility();
	}

	$modelPicker.on("change", async function () {
		const newModel = this.value || null;
		const conv = state.current_conversation;

		// On the welcome screen (no conversation yet), just stash the choice
		// in local state. It'll be applied to whichever conversation gets
		// the first send_message via the model_override arg.
		if (!conv) {
			state.current_model_override = newModel || "";
			frappe.show_alert({
				message: __("Model for next chat: ") + (newModel || state.llm_model),
				indicator: "blue",
			});
			return;
		}

		try {
			const r = await api.setConversationModel(conv, newModel);
			if (!r || !r.ok) {
				const err = (r && r.error) || {};
				frappe.show_alert({
					message: err.message || __("Couldn't set model"),
					indicator: "red",
				});
				// Revert dropdown to last-known good value
				$modelPicker.val(state.current_model_override);
				return;
			}
			state.current_model_override = newModel || "";
			frappe.show_alert({
				message: __("Model: ") + r.data.effective_model,
				indicator: "blue",
			});
		} catch (err) {
			frappe.show_alert({
				message: __("Couldn't set model: ") + (err.message || err),
				indicator: "red",
			});
			$modelPicker.val(state.current_model_override);
		}
	});

	// ---- Loading --------------------------------------------------------

	async function loadConversation(name, opts = {}) {
		if (!name) return;
		state.is_loading_conv = true;
		state.current_conversation = name;
		try {
			const data = await api.getConversation(name);
			$list.empty();
			$welcome.hide();
			renderTurns(data.messages || []);
			if (!(data.messages || []).length && !opts.keepWelcomeHidden) {
				renderEmptyConvHint();
			}
			scrollToBottom();
			// Surface the conversation title in the page header so the Desk
			// chrome above the chat carries useful context.
			const title = data.conversation?.title || __("Jarvis Chat");
			page.set_title(title);
			syncUrl(name);
			syncModelPickerToConversation(data.conversation?.model_override);
			await refreshSidebar($sidebar, $sidebarEmpty, loadConversation, archive);
		} catch (err) {
			// Conv missing / archived / not permitted - clean up and fall back
			// to welcome so a stale URL doesn't trap the user.
			state.current_conversation = null;
			if (opts.fromUrl) {
				frappe.show_alert({
					message: __("Conversation not found - opened a fresh view."),
					indicator: "orange",
				});
			}
			renderWelcome();
		} finally {
			state.is_loading_conv = false;
			$input.focus();
		}
	}

	// ---- Turn grouping --------------------------------------------------
	//
	// Render messages as logical turns: user → [collapsable tool group] →
	// assistant. The DB seq order has the assistant placeholder right after
	// the user (because the worker creates it before streaming tools), but
	// the natural read order puts assistant *after* its tool calls.

	function groupIntoTurns(messages) {
		const turns = [];
		let current = null;
		for (const msg of messages) {
			if (msg.role === "user") {
				current = { user: msg, tools: [], assistant: null };
				turns.push(current);
			} else if (current && msg.role === "tool") {
				current.tools.push(msg);
			} else if (current && msg.role === "assistant") {
				current.assistant = msg;
			} else {
				// Orphan (shouldn't happen): render flat
				turns.push({ orphan: msg });
			}
		}
		return turns;
	}

	function renderTurns(messages) {
		groupIntoTurns(messages).forEach((turn) => $list.append(buildTurnEl(turn)));
	}

	function buildTurnEl(turn) {
		const $t = $('<div class="jarvis-turn"></div>');
		if (turn.orphan) {
			$t.append(buildMessageEl(turn.orphan));
			return $t;
		}
		$t.append(buildMessageEl(turn.user));
		if (turn.tools.length) {
			const $g = buildToolGroupEl();
			const $body = $g.find(".jarvis-tool-group-body");
			turn.tools.forEach((tool) => $body.append(buildMessageEl(tool)));
			updateToolGroupCount($g);
			$t.append($g);
		}
		if (turn.assistant) $t.append(buildMessageEl(turn.assistant));
		return $t;
	}

	function renderEmptyConvHint() {
		$list.append(`
			<div class="jarvis-empty-conv">
				<p>No messages yet - ask Jarvis something to get started.</p>
			</div>
		`);
	}

	async function archive(name) {
		await api.archiveConversation(name);
		if (state.current_conversation === name) {
			state.current_conversation = null;
			page.set_title(__("Jarvis Chat"));
			renderWelcome();
		}
		await refreshSidebar($sidebar, $sidebarEmpty, loadConversation, archive);
	}

	// ---- New Chat -------------------------------------------------------

	async function onNewChat() {
		if (state.is_sending || state.is_loading_conv) return;

		// Client-side fast path: if the current conversation has zero messages,
		// just focus the input - no need to round-trip.
		if (state.current_conversation) {
			const current = state.conversations.find(
				(c) => c.name === state.current_conversation
			);
			if (current && (current.message_count || 0) === 0) {
				$input.focus();
				return;
			}
		}

		// If any other conversation in the sidebar is empty, focus it instead
		// of creating yet another empty row.
		const empty = findEmptyConversation();
		if (empty) {
			await loadConversation(empty.name);
			return;
		}

		// Server-side guarantee - won't create a duplicate empty even under a
		// race with another tab.
		const name = await api.createOrFocusEmpty();
		await loadConversation(name);
	}

	// ---- Sending --------------------------------------------------------

	async function ensureConversation() {
		if (state.current_conversation) return state.current_conversation;
		const name = await api.createOrFocusEmpty();
		state.current_conversation = name;
		return name;
	}

	async function sendMessage(textOverride) {
		if (state.is_sending) return;
		const text = (textOverride ?? $input.val() ?? "").trim();
		if (!text) return;

		setSendingState(true);
		try {
			const conv = await ensureConversation();
			$input.val("");
			autoGrowInput();

			// Pass the picker's current value (if any) so the new
			// conversation lands on it atomically - no race against the worker.
			const result = await api.sendMessage(
				conv, text, state.current_model_override || null,
			);
			if (!result.ok) {
				frappe.show_alert({ message: result.reason, indicator: "red" });
				return;
			}

			showThinking($thinking);
			await loadConversation(conv, { keepWelcomeHidden: true });
		} catch (err) {
			frappe.show_alert({
				message: __("Failed to send: ") + (err.message || err),
				indicator: "red",
			});
		} finally {
			setSendingState(false);
		}
	}

	// ---- Wiring ---------------------------------------------------------

	$send.on("click", () => sendMessage());

	$input.on("keydown", (e) => {
		if (e.key === "Enter" && !e.shiftKey) {
			e.preventDefault();
			sendMessage();
		}
	});

	$input.on("input", () => {
		autoGrowInput();
		$send.prop("disabled", state.is_sending || !$input.val().trim());
	});

	root.on("click", ".jarvis-example", function () {
		const prompt = $(this).data("prompt");
		sendMessage(prompt);
	});

	root.on("click", ".jarvis-retry-btn", async function () {
		const $btn = $(this);
		if ($btn.prop("disabled")) return;
		const msgId = $btn.data("msg");
		const originalLabel = $btn.text();
		$btn.prop("disabled", true).text(__("Retrying…"));
		try {
			const result = await api.retryMessage(msgId);
			if (!result.ok) {
				frappe.show_alert({
					message: result.reason || __("Retry failed"),
					indicator: "red",
				});
				$btn.prop("disabled", false).text(originalLabel);
				return;
			}
			showThinking($thinking);
			await loadConversation(state.current_conversation, {
				keepWelcomeHidden: true,
			});
		} catch (err) {
			frappe.show_alert({
				message: __("Retry failed: ") + (err.message || err),
				indicator: "red",
			});
			$btn.prop("disabled", false).text(originalLabel);
		}
	});

	attachRealtime({ $list, $thinking, scrollToBottom, loadConversation });

	// ---- Bootstrap ------------------------------------------------------

	// Deep-link: if the URL carries a conversation name (e.g.
	// /app/jarvis-chat/CONV-001), open it instead of the welcome view.
	const route = (frappe.get_route && frappe.get_route()) || [];
	const urlConv = route[1] ? decodeURIComponent(route[1]) : null;

	(async () => {
		// Load LLM settings first - picker rendering + visibility depend on them.
		try {
			const s = await api.getChatUiSettings();
			state.llm_auth_mode = s.llm_auth_mode || "api_key";
			state.llm_provider = s.llm_provider || "";
			state.llm_model = s.llm_model || "";
			state.subscription_models = s.subscription_models || {};
			rebuildModelPickerOptions();
			refreshModelPickerVisibility();
		} catch (e) {
			// Picker stays hidden (api_key default). Not blocking.
		}
		await refreshSidebar($sidebar, $sidebarEmpty, loadConversation, archive);
		if (urlConv) await loadConversation(urlConv, { fromUrl: true });
	})();

	autoGrowInput();
}
