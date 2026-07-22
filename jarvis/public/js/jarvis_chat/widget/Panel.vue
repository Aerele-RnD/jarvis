<template>
	<!-- Docked side chat. Kept mounted and toggled with v-show so the
	     conversation, scroll position and draft survive a close/reopen. -->
	<div
		v-show="open"
		class="jvp-root"
		:style="rootStyle"
		role="dialog"
		aria-label="Jarvis chat"
		@keydown.esc.stop="$emit('close')"
	>
		<div class="jvp-panel" ref="panelEl" tabindex="-1">
			<div class="jvp-head">
				<div class="jvp-title">
					<svg class="jvp-mark" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
						<path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" />
					</svg>
					Jarvis
				</div>
				<div class="jvp-actions">
					<button class="jvp-ib" type="button" aria-label="New chat" @click="startNewChat">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
							<path d="M12 5v14M5 12h14" />
						</svg>
					</button>
					<button class="jvp-ib" type="button" aria-label="Open full chat" @click="$emit('open-full')">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
							<path d="M15 3h6v6M21 3l-7 7M10 21H4v-6M4 21l7-7" />
						</svg>
					</button>
					<button class="jvp-ib" type="button" aria-label="Close" @click="$emit('close')">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
							<path d="M18 6 6 18M6 6l12 12" />
						</svg>
					</button>
				</div>
			</div>

			<!-- Quiet bordered note (design.md 3.7): ambient state, not an alert,
			     so no colored fill. -->
			<div v-if="contextText" class="jvp-ctx">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
					<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
					<path d="M14 2v6h6" />
				</svg>
				<div class="jvp-ctx-txt">Viewing <b>{{ contextText }}</b></div>
				<button
					class="jvp-ib jvp-ib--sm"
					type="button"
					aria-label="Stop using this page as context"
					@click="$emit('dismiss-context')"
				>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
						<path d="M18 6 6 18M6 6l12 12" />
					</svg>
				</button>
			</div>

			<div class="jvp-body" ref="bodyEl">
				<div v-if="loading" class="jvp-center">Restoring your last conversation…</div>

				<div v-else-if="loadError && !shownMessages.length" class="jvp-center">
					<div class="jvp-err">{{ loadError }}</div>
					<button class="jvp-btn-subtle" type="button" @click="load">Retry</button>
				</div>

				<!-- Welcome: greeting + a few starting points, so an empty panel
				     suggests what to do rather than showing a blank box. -->
				<div v-else-if="!shownMessages.length && !stream.live && !thinking" class="jvp-welcome">
					<div class="jvp-greet">{{ greeting }}</div>
					<p class="jvp-greet-sub">
						{{
							contextText
								? `Jarvis can see ${contextText} while you are on this page.`
								: "Ask about your ERP data, run a workflow, or draft something."
						}}
					</p>
					<div class="jvp-cards">
						<button
							v-for="s in suggestions"
							:key="s.title"
							class="jvp-card"
							type="button"
							@click="useSuggestion(s.prompt)"
						>
							<span class="jvp-card-t">{{ s.title }}</span>
							<span class="jvp-card-p">{{ s.prompt }}</span>
						</button>
					</div>
				</div>

				<div v-else class="jvp-msgs">
					<div
						v-for="m in shownMessages"
						:key="m.name"
						:class="m.role === 'user' ? 'jvp-m-user' : 'jvp-m-bot'"
					>{{ m.content }}</div>
					<div v-if="stream.live && stream.live.text" class="jvp-m-bot">{{ stream.live.text }}</div>
					<!-- Waiting for the first token: a labelled state, not a bare
					     spinner, so the user knows the turn was accepted. -->
					<div v-else-if="thinking" class="jvp-think" role="status" aria-live="polite">
						<span class="jvp-think-dots" aria-hidden="true"><i></i><i></i><i></i></span>
						<span class="jvp-think-txt">Working…</span>
					</div>
					<div v-if="loadError && shownMessages.length" class="jvp-inline-err">
						<span class="jvp-err">{{ loadError }}</span>
						<button class="jvp-btn-subtle" type="button" @click="retryLast">Retry</button>
					</div>
				</div>
			</div>

			<!-- A blocked write is the one thing here the user must act on, so it
			     is the only place the panel raises its voice. -->
			<div v-if="stream.pending.length" class="jvp-pending">
				<div v-for="p in stream.pending" :key="p.token" class="jvp-pending-row">
					<div class="jvp-pending-txt">{{ p.summary || "Jarvis wants to make a change." }}</div>
					<div class="jvp-pending-acts">
						<button class="jvp-btn-subtle" type="button" @click="$emit('open-full')">
							Review in full chat
						</button>
						<button
							class="jvp-btn-solid"
							type="button"
							:disabled="resolving === p.token"
							@click="resolvePending(p.token)"
						>{{ resolving === p.token ? "Confirming…" : "Confirm" }}</button>
					</div>
				</div>
			</div>

			<div class="jvp-foot">
				<div class="jvp-comp" :class="{ 'jvp-comp--focus': composerFocused }">
					<textarea
						class="jvp-comp-text"
						ref="textareaEl"
						rows="1"
						:placeholder="contextText ? `Ask about ${contextText}…` : 'Ask Jarvis…'"
						v-model="draft"
						@focus="composerFocused = true"
						@blur="composerFocused = false"
						@input="autoGrow"
						@keydown.enter.exact.prevent="send"
					></textarea>
					<div class="jvp-comp-bar">
						<span class="jvp-comp-hint">{{ hint }}</span>
						<button
							v-if="stream.live"
							class="jvp-send jvp-send--stop"
							type="button"
							aria-label="Stop generating"
							@click="stop"
						>
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
								<rect x="7" y="7" width="10" height="10" rx="2" />
							</svg>
						</button>
						<button
							v-else
							class="jvp-send"
							type="button"
							aria-label="Send message"
							:disabled="!canSend"
							@click="send"
						>
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
								<path d="M12 19V5M5 12l7-7 7 7" />
							</svg>
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed, ref, watch, nextTick, onMounted, onBeforeUnmount } from "vue";
import { contextLabel } from "./desk_context.mjs";
import { greetingLine, suggestionsFor } from "./panel_welcome.mjs";
import { emptyStream, applyEvent, visibleMessages } from "./chat_stream.mjs";
import {
	listConversations,
	getConversation,
	sendMessage,
	stopRun,
	confirmTool,
} from "./panel_api.mjs";

const props = defineProps({
	open: { type: Boolean, default: false },
	context: { type: Object, default: null },
	// Computed by panel_anchor.panelLayout from wherever the user dragged the
	// FAB. The panel is a floating mini window, so it has no fixed home.
	layout: { type: Object, default: null },
});
defineEmits(["close", "open-full", "dismiss-context"]);

const panelEl = ref(null);
const bodyEl = ref(null);
const textareaEl = ref(null);

const convId = ref("");
const messages = ref([]);
const stream = ref(emptyStream());
const loading = ref(false);
const loadError = ref("");
const draft = ref("");
const sending = ref(false);
const composerFocused = ref(false);
const resolving = ref("");
const lastSent = ref("");

const contextText = computed(() => contextLabel(props.context));

// The panel is positioned, not docked: left/top/width/height all come from the
// FAB's current spot so dragging the launcher moves its window with it.
const rootStyle = computed(() => {
	const l = props.layout;
	if (!l) return { display: "none" };
	return {
		left: `${l.left}px`,
		top: `${l.top}px`,
		width: `${l.width}px`,
		height: `${l.height}px`,
	};
});
// Tool rows and empty shells are filtered out: this panel is text-only, and
// the raw list is mostly machine chatter (see chat_stream.visibleMessages).
const shownMessages = computed(() => visibleMessages(messages.value));
// A turn is in flight from the moment the POST is away until the first token
// lands. Without this the panel looks inert for the whole worker round-trip.
const greeting = computed(() => {
	const who =
		window.frappe?.boot?.user?.full_name || window.frappe?.session?.user_fullname || "";
	return greetingLine(new Date().getHours(), who);
});
const suggestions = computed(() => suggestionsFor(props.context));

// A suggestion is a starting point, not a command: it fills the composer so
// the user can edit before sending.
function useSuggestion(prompt) {
	draft.value = prompt;
	nextTick(() => {
		autoGrow();
		textareaEl.value?.focus();
	});
}

const thinking = computed(() => sending.value || (stream.value.busy && !stream.value.live));
const canSend = computed(() => draft.value.trim().length > 0 && !sending.value && !stream.value.live);
const hint = computed(() => {
	if (stream.value.live) return "Jarvis is replying…";
	if (sending.value) return "Sending…";
	return "Enter to send";
});

async function scrollToBottom() {
	await nextTick();
	if (bodyEl.value) bodyEl.value.scrollTop = bodyEl.value.scrollHeight;
}

function autoGrow() {
	const el = textareaEl.value;
	if (!el) return;
	el.style.height = "auto";
	el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
}

// The panel's contract is to continue where the user left off, so the first
// open resolves the newest conversation and restores it. A user with no history
// gets the empty state, and an id is minted on first send.
async function load() {
	loading.value = true;
	loadError.value = "";
	try {
		if (!convId.value) {
			const list = await listConversations();
			convId.value = Array.isArray(list) && list.length ? list[0].name : "";
		}
		if (!convId.value) {
			messages.value = [];
			return;
		}
		const conv = await getConversation(convId.value);
		messages.value = Array.isArray(conv?.messages) ? conv.messages : [];
		await scrollToBottom();
	} catch (e) {
		loadError.value = "Could not load your conversation.";
	} finally {
		loading.value = false;
	}
}

function startNewChat() {
	convId.value = "";
	messages.value = [];
	stream.value = emptyStream();
	loadError.value = "";
	draft.value = "";
	nextTick(() => textareaEl.value?.focus());
}

async function send() {
	const text = draft.value.trim();
	if (!text || sending.value || stream.value.live) return;
	sending.value = true;
	loadError.value = "";
	lastSent.value = text;

	// Optimistic echo so the panel feels immediate. run:end reloads from the
	// durable record, which replaces this.
	messages.value.push({ name: `local-${Date.now()}`, role: "user", content: text });
	draft.value = "";
	await nextTick();
	autoGrow();
	await scrollToBottom();

	try {
		// Context is read at SEND time, not at open time: a conversation outlives
		// the page it started on, and pinning it would leave the agent silently
		// answering about the wrong record after a navigation.
		const res = await sendMessage(convId.value, text, props.context);
		if (res?.conversation_id) convId.value = res.conversation_id;
		stream.value = { ...stream.value, busy: true };
	} catch (e) {
		sending.value = false;
		loadError.value = "Could not send. Your message was not delivered.";
	}
}

function retryLast() {
	if (!lastSent.value) return;
	draft.value = lastSent.value;
	loadError.value = "";
	// Drop the optimistic echo that never made it to the server.
	const i = messages.value.findIndex((m) => String(m.name).startsWith("local-"));
	if (i !== -1) messages.value.splice(i, 1);
	send();
}

async function stop() {
	if (!stream.value.live) return;
	try {
		await stopRun(convId.value, stream.value.live.runId);
	} catch (e) {
		/* the run ends on its own; nothing useful to say here */
	}
}

async function resolvePending(token) {
	if (resolving.value) return;
	resolving.value = token;
	try {
		await confirmTool(token, convId.value);
		stream.value = applyEvent(stream.value, { kind: "action:resolved", token });
	} catch (e) {
		loadError.value = "Could not confirm that action.";
	} finally {
		resolving.value = "";
	}
}

// The Desk already holds an authenticated socket, so the panel joins it rather
// than dialling a second one the way the PWA has to.
function onRealtime(payload) {
	const conv = payload?.conversation_id || payload?.conversation;
	if (!conv || conv !== convId.value) return;

	const next = applyEvent(stream.value, payload);

	if (next.reload) {
		// Clear the flag before reloading so a second frame cannot double-fetch.
		stream.value = { ...next, reload: false, error: "" };
		sending.value = false;
		if (next.error) loadError.value = next.error;
		load();
		return;
	}

	stream.value = next;
	if (next.live) {
		sending.value = false;
		scrollToBottom();
	}
	if (next.error) loadError.value = next.error;
}

// Load lazily on first open, not at mount: the FAB is on every Desk page and
// most page views never open the panel.
let loadedOnce = false;
watch(
	() => props.open,
	async (isOpen) => {
		if (!isOpen) return;
		await nextTick();
		panelEl.value?.focus();
		if (loadedOnce) return;
		loadedOnce = true;
		load();
	}
);

onMounted(() => {
	window.frappe?.realtime?.on?.("jarvis:event", onRealtime);
});

onBeforeUnmount(() => {
	window.frappe?.realtime?.off?.("jarvis:event", onRealtime);
});

defineExpose({ load, startNewChat, convId });
</script>

<style scoped>
/* Desk CSS variables only — the Desk already stamps the theme, so light/dark
   comes free and no dark: variants are needed (design.md 6). */
/* A mini chat window, not a full-height dock: left/top/width/height are set
   inline from panel_anchor.panelLayout() so the window follows the FAB
   wherever the user dragged it. */
.jvp-root {
	position: fixed;
	z-index: 1029; /* under Frappe modals (1050), over page content */
	display: flex;
	pointer-events: none;
}

.jvp-panel {
	pointer-events: auto;
	display: flex;
	flex-direction: column;
	flex: 1;
	min-height: 0;
	background: var(--card-bg, #fff);
	border: 1px solid var(--border-color);
	border-radius: 12px;
	box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
	overflow: hidden;
	font-size: 14px;
	letter-spacing: 0.02em;
	color: var(--text-color);
	outline: none;
}

/* design.md 3.2: overlays fade + scale 0.98 -> 1 in 100ms. Not a slide — this
   is the same motion every other overlay in the product uses. Gated so
   reduced-motion users get an instant swap. */
@media (prefers-reduced-motion: no-preference) {
	.jvp-panel {
		animation: jvp-in 100ms ease-out;
	}
}
@keyframes jvp-in {
	from {
		opacity: 0;
		transform: scale(0.98);
	}
	to {
		opacity: 1;
		transform: scale(1);
	}
}

.jvp-head {
	height: 42px;
	flex: none;
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 0 8px 0 12px;
	border-bottom: 1px solid var(--border-color);
}
.jvp-title {
	display: flex;
	align-items: center;
	gap: 8px;
	font-weight: 600;
}
.jvp-mark {
	width: 16px;
	height: 16px;
	flex: none;
}
.jvp-actions {
	display: flex;
	align-items: center;
	gap: 2px;
}

.jvp-ib {
	width: 28px;
	height: 28px;
	flex: none;
	border: none;
	background: transparent;
	border-radius: 8px;
	color: var(--text-muted);
	cursor: pointer;
	display: flex;
	align-items: center;
	justify-content: center;
	transition: background-color 0.12s ease;
}
.jvp-ib:hover {
	background: var(--fg-hover-color, rgba(0, 0, 0, 0.05));
}
.jvp-ib:focus-visible {
	outline: 2px solid var(--border-primary, #999);
	outline-offset: 1px;
}
.jvp-ib svg {
	width: 16px;
	height: 16px;
}
.jvp-ib--sm {
	width: 24px;
	height: 24px;
}
.jvp-ib--sm svg {
	width: 14px;
	height: 14px;
}

.jvp-ctx {
	margin: 12px 12px 0;
	display: flex;
	align-items: center;
	gap: 8px;
	border: 1px solid var(--border-color);
	border-radius: 10px;
	padding: 7px 8px;
}
.jvp-ctx svg {
	width: 16px;
	height: 16px;
	flex: none;
	color: var(--text-muted);
}
.jvp-ctx-txt {
	flex: 1;
	min-width: 0;
	font-size: 12px;
	line-height: 1.35;
	color: var(--text-muted);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.jvp-ctx-txt b {
	font-weight: 600;
	color: var(--text-color);
}

.jvp-body {
	flex: 1;
	min-height: 0;
	overflow-y: auto;
	padding: 14px 12px;
}

.jvp-center {
	height: 100%;
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	gap: 9px;
	text-align: center;
	padding: 22px;
	color: var(--text-muted);
}
.jvp-empty-ic {
	width: 28px;
	height: 28px;
}
.jvp-empty-t {
	font-size: 16px;
	font-weight: 500;
	color: var(--text-color);
}
.jvp-empty-d {
	font-size: 14px;
	line-height: 1.5;
	max-width: 30ch;
}
.jvp-err {
	font-size: 13.5px;
	color: var(--text-danger, #c0392b);
}

/* ---- welcome ---- */
.jvp-welcome {
	display: flex;
	flex-direction: column;
	gap: 6px;
	padding: 6px 2px 2px;
}
.jvp-greet {
	font-size: 19px;
	font-weight: 600;
	color: var(--text-color);
	letter-spacing: -0.01em;
}
.jvp-greet-sub {
	margin: 0;
	font-size: 13.5px;
	line-height: 1.5;
	color: var(--text-muted);
}
.jvp-cards {
	display: flex;
	flex-direction: column;
	gap: 8px;
	margin-top: 12px;
}
/* Cards are bordered and flat: selection and hover are colour shifts, never a
   lift (design.md 1.3, 5 row 2). */
.jvp-card {
	display: flex;
	flex-direction: column;
	gap: 3px;
	text-align: left;
	padding: 10px 12px;
	border: 1px solid var(--border-color);
	border-radius: 10px;
	background: transparent;
	font: inherit;
	letter-spacing: inherit;
	cursor: pointer;
	transition: background-color 0.12s ease, border-color 0.12s ease;
}
.jvp-card:hover {
	background: var(--control-bg, #f3f3f3);
}
.jvp-card:focus-visible {
	outline: 2px solid var(--border-primary, #999);
	outline-offset: 1px;
}
.jvp-card-t {
	font-size: 13.5px;
	font-weight: 500;
	color: var(--text-color);
}
.jvp-card-p {
	font-size: 12.5px;
	line-height: 1.45;
	color: var(--text-muted);
}
.jvp-inline-err {
	display: flex;
	align-items: center;
	gap: 10px;
	flex-wrap: wrap;
}

.jvp-msgs {
	display: flex;
	flex-direction: column;
	gap: 14px;
}
.jvp-m-user {
	align-self: flex-end;
	max-width: 84%;
	background: var(--control-bg, #f3f3f3);
	border-radius: 12px;
	padding: 8px 12px;
	line-height: 1.5;
	white-space: pre-wrap;
	overflow-wrap: anywhere;
}
.jvp-m-bot {
	max-width: 94%;
	line-height: 1.5;
	white-space: pre-wrap;
	overflow-wrap: anywhere;
}

.jvp-pending {
	flex: none;
	border-top: 1px solid var(--border-color);
	padding: 10px 12px;
}
.jvp-pending-row {
	display: flex;
	flex-direction: column;
	gap: 8px;
}
.jvp-pending-txt {
	font-size: 13px;
	line-height: 1.45;
	color: var(--text-color);
}
.jvp-pending-acts {
	display: flex;
	gap: 8px;
	justify-content: flex-end;
}

.jvp-foot {
	flex: none;
	border-top: 1px solid var(--border-color);
	padding: 12px;
}

/* One container holds the text and its controls, and the send button lives
   inside it: at 400px a separate button row costs a message of vertical
   space. */
.jvp-comp {
	background: var(--control-bg, #f3f3f3);
	border: 1px solid transparent;
	border-radius: 12px;
	padding: 9px 9px 8px;
	transition: background-color 0.12s ease, border-color 0.12s ease, box-shadow 0.12s ease;
}
.jvp-comp--focus,
.jvp-comp:focus-within {
	background: var(--card-bg, #fff);
	border-color: var(--border-color);
	box-shadow: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
}
.jvp-comp-text {
	width: 100%;
	border: none;
	background: transparent;
	resize: none;
	font: inherit;
	letter-spacing: inherit;
	color: var(--text-color);
	line-height: 1.5;
	padding: 1px 3px 8px;
	max-height: 120px;
	outline: none;
}
.jvp-comp-bar {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 8px;
}
.jvp-comp-hint {
	font-size: 11.5px;
	color: var(--text-muted);
}

/* The one solid button on this surface (design.md 3.1). */
.jvp-send {
	width: 28px;
	height: 28px;
	flex: none;
	border: none;
	border-radius: 8px;
	cursor: pointer;
	background: var(--text-color);
	color: var(--card-bg, #fff);
	display: flex;
	align-items: center;
	justify-content: center;
	transition: opacity 0.12s ease;
}
.jvp-send svg {
	width: 16px;
	height: 16px;
}
.jvp-send:hover {
	opacity: 0.88;
}
.jvp-send:focus-visible {
	outline: 2px solid var(--border-primary, #999);
	outline-offset: 2px;
}
.jvp-send[disabled] {
	background: var(--control-bg, #ededed);
	color: var(--text-muted);
	cursor: not-allowed;
}
.jvp-send--stop {
	background: var(--control-bg, #ededed);
	color: var(--text-color);
}

.jvp-btn-subtle {
	height: 28px;
	padding: 0 10px;
	border: none;
	border-radius: 8px;
	background: var(--control-bg, #f3f3f3);
	color: var(--text-color);
	font: inherit;
	cursor: pointer;
}
.jvp-btn-subtle:hover {
	background: var(--fg-hover-color, rgba(0, 0, 0, 0.08));
}
.jvp-btn-solid {
	height: 28px;
	padding: 0 12px;
	border: none;
	border-radius: 8px;
	cursor: pointer;
	background: var(--text-color);
	color: var(--card-bg, #fff);
	font: inherit;
	font-weight: 500;
}
.jvp-btn-solid[disabled] {
	opacity: 0.6;
	cursor: not-allowed;
}

/* ---- waiting for a reply ---- */
.jvp-think {
	display: flex;
	align-items: center;
	gap: 9px;
	color: var(--text-muted);
	font-size: 13.5px;
}
.jvp-think-dots {
	display: inline-flex;
	align-items: flex-end;
	gap: 3px;
	height: 12px;
}
.jvp-think-dots i {
	width: 4px;
	height: 4px;
	border-radius: 999px;
	background: currentColor;
	opacity: 0.35;
}
@media (prefers-reduced-motion: no-preference) {
	.jvp-think-dots i {
		animation: jvp-dot 1.2s infinite ease-in-out;
	}
	.jvp-think-dots i:nth-child(2) {
		animation-delay: 0.15s;
	}
	.jvp-think-dots i:nth-child(3) {
		animation-delay: 0.3s;
	}
}
/* Progress feedback, not decoration — the one animation design.md's
   no-motion rule does not cover, and it is gated on motion-safe anyway. */
@keyframes jvp-dot {
	0%,
	80%,
	100% {
		transform: translateY(0);
		opacity: 0.35;
	}
	40% {
		transform: translateY(-4px);
		opacity: 1;
	}
}
</style>
