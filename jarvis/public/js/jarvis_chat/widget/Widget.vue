<template>
	<!-- Frappe-native mini chat (matches the imported "Jarvis Chat" design),
	     floating on every ERP Desk page with auto-context of the page. -->
	<div class="jvw-root">
		<div class="jvw-launch">
			<!-- panel (plain <div>s — semantic <header>/<section> get re-parented
			     by Frappe's toolbar) -->
			<div v-show="open" class="jvw-panel">
				<div class="jvw-head">
					<div class="jvw-mk"><svg viewBox="0 0 24 24" width="15" height="15" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg></div>
					<div class="jvw-head-text">
						<span class="jvw-name">Jarvis</span>
						<span v-if="context" class="jvw-sub jvw-sub-ctx">{{ context.label }}</span>
						<span v-else class="jvw-sub jvw-sub-on"><i></i> Connected to ERPNext</span>
					</div>
					<div class="jvw-ctl">
						<button type="button" class="jvw-ibtn" title="Open full screen" @click="expand">
							<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" /></svg>
						</button>
						<button type="button" class="jvw-ibtn" title="Minimize" @click="minimize">
							<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 12h14" /></svg>
						</button>
					</div>
				</div>

				<div ref="bodyEl" class="jvw-body">
					<template v-if="visibleMessages.length">
						<template v-for="m in visibleMessages" :key="m.name">
							<div v-if="m.role === 'user'" class="jvw-row jvw-row-u">
								<div class="jvw-bub-u">{{ m.content }}</div>
							</div>
							<div v-else class="jvw-row">
								<div class="jvw-av"><svg viewBox="0 0 24 24" width="13" height="13" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg></div>
								<div v-if="m.error" class="jvw-bub-err">{{ m.error }}</div>
								<div v-else class="jvw-md" v-html="render(m.content)"></div>
							</div>
						</template>
					</template>
					<template v-else>
						<div class="jvw-welcome">
							<div class="jvw-welcome-mk"><svg viewBox="0 0 24 24" width="20" height="20" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg></div>
							<div class="jvw-welcome-h">Hi {{ firstName }} 👋</div>
							<div class="jvw-welcome-s">
								Ask about <b v-if="context">{{ context.label }}</b><template v-else>this page</template> or start a
								workflow without leaving it.
							</div>
						</div>
						<div class="jvw-sugs">
							<button v-for="s in starterPrompts" :key="s" type="button" class="jvw-sug" @click="send(s)">{{ s }}</button>
						</div>
					</template>

					<div v-if="waiting" class="jvw-row">
						<div class="jvw-av"><svg viewBox="0 0 24 24" width="13" height="13" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg></div>
						<div class="jvw-typing"><span></span><span></span><span></span></div>
					</div>
				</div>

				<div v-if="files.length" class="jvw-files">
					<span v-for="(f, i) in files" :key="i" class="jvw-file">📎 {{ f.file_name }}<button type="button" @click="files.splice(i, 1)">×</button></span>
				</div>

				<div class="jvw-foot">
					<div class="jvw-input-wrap">
						<button type="button" class="jvw-attach" title="Attach a file" :disabled="isSending" @click="attach">
							<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a5 5 0 0 1-7.07-7.07l9.19-9.19a3.5 3.5 0 0 1 4.95 4.95l-9.2 9.19a1.5 1.5 0 0 1-2.12-2.12l8.49-8.49" /></svg>
						</button>
						<textarea ref="input" v-model="draft" rows="1" class="jvw-input" :placeholder="composerPlaceholder" @keydown="onKeydown" @input="autoGrow"></textarea>
						<button type="button" class="jvw-send" :disabled="!canSend" title="Send" @click="submitDraft">
							<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="#fff" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
						</button>
					</div>
				</div>
			</div>

			<button type="button" class="jvw-fab" :title="open ? 'Minimize' : hasUnread ? 'Jarvis — new reply' : 'Ask Jarvis'" @click="toggle">
				<svg v-if="open" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
				<template v-else>
					<svg viewBox="0 0 24 24" width="24" height="24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
					<span v-if="hasUnread" class="jvw-fab-dot"></span>
				</template>
			</button>
		</div>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick } from "vue";
import { renderMarkdown } from "../messages.js";
import * as api from "../api.js";

const open = ref(false);
const hasUnread = ref(false);
const booted = ref(false);

const conversationId = ref(null);
const messages = ref([]);
const isSending = ref(false);
const waiting = ref(false);

const draft = ref("");
const files = ref([]);
const input = ref(null);
const bodyEl = ref(null);

const firstName = (
	(window.frappe && (frappe.session.user_fullname || frappe.session.user)) || "there"
)
	.split(/\s+/)[0];

const visibleMessages = computed(() =>
	messages.value.filter((m) => m.role === "user" || m.role === "assistant"),
);
function render(text) {
	return renderMarkdown(text || "");
}

// ---- context (auto-awareness of the doc / list you're viewing) ----
const context = ref(null);
const composerPlaceholder = computed(() =>
	context.value ? `Ask about this ${context.value.doctypeLabel}…` : "Ask Jarvis anything…",
);
const canSend = computed(
	() => (draft.value.trim().length > 0 || files.value.length > 0) && !isSending.value,
);
const starterPrompts = computed(() => {
	const d = context.value?.doctype;
	if (d) {
		const n = d.toLowerCase();
		return [`Summarise this ${n}`, `What should I check here?`];
	}
	return ["What's overdue this month?", "Show my open tasks"];
});

function readContext() {
	try {
		const r = (window.frappe && frappe.get_route && frappe.get_route()) || [];
		if (r[0] === "Form" && r[1]) {
			context.value = {
				doctype: r[1],
				name: r[2] || "",
				doctypeLabel: r[1].toLowerCase(),
				label: r[2] ? `${r[1]} · ${r[2]}` : r[1],
			};
		} else if (r[0] === "List" && r[1]) {
			context.value = {
				doctype: r[1],
				name: "",
				doctypeLabel: `${r[1].toLowerCase()} list`,
				label: `${r[1]} (list)`,
			};
		} else {
			context.value = null;
		}
	} catch (e) {
		context.value = null;
	}
}

function scrollBottom() {
	const el = bodyEl.value;
	if (el) el.scrollTop = el.scrollHeight;
}

// ---- panel controls ----
function toggle() {
	if (open.value) minimize();
	else openPanel();
}
async function openPanel() {
	api.warmSession();
	open.value = true;
	hasUnread.value = false;
	if (!booted.value) await boot();
	await nextTick();
	input.value?.focus();
	scrollBottom();
}
function minimize() {
	open.value = false;
}
function expand() {
	open.value = false;
	// Open the full chat SPA (the new canonical chat page), not the retired
	// Desk page. Same backend + conversation, so the thread carries over.
	window.location.assign("/jarvis");
}

// ---- composer ----
function onKeydown(e) {
	if (e.key === "Enter" && !e.shiftKey) {
		e.preventDefault();
		submitDraft();
	}
}
function autoGrow() {
	const el = input.value;
	if (!el) return;
	el.style.height = "auto";
	el.style.height = Math.min(el.scrollHeight, 120) + "px";
}
function attach() {
	if (isSending.value) return;
	// eslint-disable-next-line no-new
	new frappe.ui.FileUploader({
		allow_multiple: true,
		folder: "Home/Attachments",
		on_success(fileDoc) {
			if (fileDoc && fileDoc.file_url) {
				files.value.push({
					file_url: fileDoc.file_url,
					file_name: fileDoc.file_name || fileDoc.file_url,
				});
			}
		},
	});
}
function submitDraft() {
	if (!canSend.value) return;
	const text = draft.value.trim();
	const attachments = files.value.slice();
	draft.value = "";
	files.value = [];
	nextTick(autoGrow);
	send({ text, attachments });
}

// ---- data + realtime ----
async function boot() {
	booted.value = true;
	frappe.realtime.on("jarvis:event", onEvent);
	try {
		const convs = await api.listConversations();
		if (convs && convs.length) {
			conversationId.value = convs[0].name;
			const data = await api.getConversation(conversationId.value);
			messages.value = data?.messages || [];
		}
	} catch (e) {
		/* fresh start */
	}
}

async function send(payload) {
	const text = typeof payload === "string" ? payload : payload?.text || "";
	const attachments = (payload && payload.attachments) || [];
	if (!text && !attachments.length) return;

	if (!conversationId.value) {
		const conv = await api.createOrFocusEmpty();
		conversationId.value = conv?.name || conv;
	}
	isSending.value = true;
	waiting.value = true;

	const marker = attachments.length ? "📎 " + attachments.map((a) => a.file_name).join(", ") : "";
	const optimistic = [text, marker].filter(Boolean).join("\n\n");
	messages.value = [
		...messages.value,
		{ name: `tmp-${Date.now()}`, role: "user", content: optimistic, streaming: false },
	];
	await nextTick();
	scrollBottom();

	try {
		await api.sendMessage(conversationId.value, text, undefined, attachments, context.value || undefined);
	} catch (e) {
		isSending.value = false;
		waiting.value = false;
		frappe.show_alert({ message: __("Failed to send"), indicator: "red" });
	}
}

function onEvent(payload) {
	if (payload.conversation_id !== conversationId.value) return;
	switch (payload.kind) {
		case "run:start":
			reload();
			waiting.value = true;
			break;
		case "assistant:delta": {
			waiting.value = false;
			const m = messages.value.find((x) => x.name === payload.message_id);
			if (m) {
				m.content = payload.text;
				m.streaming = true;
			}
			if (!open.value) hasUnread.value = true;
			nextTick(scrollBottom);
			break;
		}
		case "run:end": {
			const m = messages.value.find((x) => x.name === payload.message_id);
			if (m) m.streaming = false;
			waiting.value = false;
			isSending.value = false;
			if (!open.value) hasUnread.value = true;
			break;
		}
		case "run:error":
			waiting.value = false;
			isSending.value = false;
			break;
	}
}

async function reload() {
	if (!conversationId.value) return;
	const data = await api.getConversation(conversationId.value);
	messages.value = data?.messages || [];
	await nextTick();
	scrollBottom();
}

function onRouteChange() {
	readContext();
}

onMounted(() => {
	readContext();
	if (window.frappe && frappe.router) frappe.router.on("change", onRouteChange);
	try {
		if (sessionStorage.getItem("jarvis-widget-open") === "1") {
			sessionStorage.removeItem("jarvis-widget-open");
			openPanel();
		}
	} catch (e) {
		/* sessionStorage unavailable */
	}
});

onBeforeUnmount(() => {
	try {
		frappe.realtime.off("jarvis:event", onEvent);
	} catch (e) {
		/* not registered */
	}
});

defineExpose({ openPanel });
</script>

<style scoped>
/* Frappe-native design tokens, scoped to the widget (it lives in <body>). */
.jvw-root {
	--surface: #ffffff;
	--surface-1: #f7f7f8;
	--surface-2: #f1f1f3;
	--surface-3: #ececef;
	--border: #e8e8ec;
	--border-2: #dfdfe4;
	--text: #171717;
	--text-2: #4a4a4f;
	--text-3: #83838b;
	--accent: #171717;
	--green: #16a34a;
	--green-bg: #edf8f0;
	--red: #dc2626;
	--red-bg: #fdf0ef;
	--red-bd: #f5d4d1;
	font-family: "Inter", system-ui, -apple-system, sans-serif;
}

.jvw-launch {
	position: fixed;
	bottom: 22px;
	right: 22px;
	z-index: 1120;
	display: flex;
	flex-direction: column;
	align-items: flex-end;
	gap: 14px;
}

/* ---- panel ---- */
.jvw-panel {
	width: 372px;
	height: min(540px, calc(100vh - 110px));
	background: var(--surface);
	border: 1px solid var(--border-2);
	border-radius: 16px;
	box-shadow: 0 16px 48px rgba(20, 20, 30, 0.18);
	display: flex;
	flex-direction: column;
	overflow: hidden;
	color: var(--text);
}
.jvw-head {
	display: flex;
	align-items: center;
	gap: 9px;
	padding: 12px 14px;
	border-bottom: 1px solid var(--border);
	flex: none;
}
.jvw-mk {
	width: 28px;
	height: 28px;
	border-radius: 7px;
	background: var(--accent);
	display: flex;
	align-items: center;
	justify-content: center;
	flex: none;
}
.jvw-head-text {
	display: flex;
	flex-direction: column;
	line-height: 1.15;
	min-width: 0;
}
.jvw-name {
	font-size: 13.5px;
	font-weight: 600;
}
.jvw-sub {
	font-size: 10.5px;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}
.jvw-sub-on {
	display: flex;
	align-items: center;
	gap: 4px;
	color: var(--green);
	font-weight: 500;
}
.jvw-sub-on i {
	width: 5px;
	height: 5px;
	border-radius: 50%;
	background: var(--green);
}
.jvw-sub-ctx {
	color: var(--text-3);
	font-weight: 500;
	font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.jvw-ctl {
	margin-left: auto;
	display: flex;
	gap: 2px;
}
.jvw-ibtn {
	width: 28px;
	height: 28px;
	display: flex;
	align-items: center;
	justify-content: center;
	background: transparent;
	border: none;
	border-radius: 6px;
	cursor: pointer;
	color: var(--text-3);
}
.jvw-ibtn:hover {
	background: var(--surface-2);
	color: var(--text-2);
}

/* ---- body ---- */
.jvw-body {
	flex: 1;
	overflow-y: auto;
	padding: 16px 14px;
	display: flex;
	flex-direction: column;
	gap: 14px;
}
.jvw-row {
	display: flex;
	gap: 9px;
}
.jvw-row-u {
	justify-content: flex-end;
}
.jvw-av {
	width: 24px;
	height: 24px;
	flex: none;
	border-radius: 6px;
	background: var(--accent);
	display: flex;
	align-items: center;
	justify-content: center;
	margin-top: 1px;
}
.jvw-bub-u {
	max-width: 82%;
	background: var(--surface-1);
	border: 1px solid var(--border);
	border-radius: 11px 11px 4px 11px;
	padding: 8px 11px;
	font-size: 12.5px;
	line-height: 1.5;
	color: var(--text);
	white-space: pre-wrap;
}
.jvw-bub-err {
	flex: 1;
	font-size: 12px;
	color: #b42318;
	background: var(--red-bg);
	border: 1px solid var(--red-bd);
	border-radius: 4px 11px 11px 11px;
	padding: 8px 11px;
	line-height: 1.5;
}
.jvw-md {
	flex: 1;
	min-width: 0;
	font-size: 12.5px;
	line-height: 1.55;
	color: var(--text);
	padding-top: 2px;
}
.jvw-md :deep(p) {
	margin: 0 0 7px;
}
.jvw-md :deep(p:last-child) {
	margin-bottom: 0;
}
.jvw-md :deep(a) {
	color: var(--accent);
	font-weight: 500;
}
.jvw-md :deep(table) {
	width: 100%;
	border-collapse: collapse;
	font-size: 11.5px;
	border: 1px solid var(--border);
	border-radius: 8px;
	overflow: hidden;
	margin: 4px 0;
}
.jvw-md :deep(th) {
	text-align: left;
	font-weight: 550;
	color: var(--text-3);
	background: var(--surface-1);
	padding: 6px 9px;
	border-bottom: 1px solid var(--border);
}
.jvw-md :deep(td) {
	padding: 6px 9px;
	border-bottom: 1px solid var(--border);
}

.jvw-welcome {
	text-align: center;
	padding: 8px 0 4px;
}
.jvw-welcome-mk {
	width: 38px;
	height: 38px;
	border-radius: 10px;
	background: var(--accent);
	display: flex;
	align-items: center;
	justify-content: center;
	margin: 0 auto 9px;
}
.jvw-welcome-h {
	font-size: 14px;
	font-weight: 600;
}
.jvw-welcome-s {
	font-size: 12px;
	color: var(--text-3);
	margin-top: 2px;
	line-height: 1.45;
}
.jvw-sugs {
	display: flex;
	flex-direction: column;
	gap: 7px;
}
.jvw-sug {
	text-align: left;
	padding: 8px 11px;
	background: var(--surface);
	border: 1px solid var(--border);
	border-radius: 8px;
	font-family: inherit;
	font-size: 12px;
	color: var(--text-2);
	font-weight: 500;
	cursor: pointer;
}
.jvw-sug:hover {
	background: var(--surface-1);
	border-color: var(--border-2);
}
.jvw-typing {
	display: flex;
	align-items: center;
	gap: 4px;
	padding-top: 7px;
}
.jvw-typing span {
	width: 5px;
	height: 5px;
	border-radius: 50%;
	background: var(--text-3);
	animation: jvw-dot 1.1s infinite;
}
.jvw-typing span:nth-child(2) {
	animation-delay: 0.18s;
}
.jvw-typing span:nth-child(3) {
	animation-delay: 0.36s;
}
@keyframes jvw-dot {
	0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
	30% { transform: translateY(-4px); opacity: 1; }
}

/* ---- files + composer ---- */
.jvw-files {
	display: flex;
	flex-wrap: wrap;
	gap: 6px;
	padding: 0 14px 6px;
}
.jvw-file {
	display: inline-flex;
	align-items: center;
	gap: 5px;
	font-size: 11px;
	padding: 3px 5px 3px 9px;
	border-radius: 999px;
	color: var(--text-2);
	background: var(--surface-1);
	border: 1px solid var(--border);
}
.jvw-file button {
	border: none;
	background: transparent;
	cursor: pointer;
	font-size: 14px;
	line-height: 1;
	color: inherit;
}
.jvw-foot {
	padding: 10px 12px;
	border-top: 1px solid var(--border);
	flex: none;
}
.jvw-input-wrap {
	display: flex;
	align-items: flex-end;
	gap: 6px;
	border: 1px solid var(--border-2);
	border-radius: 11px;
	padding: 4px 4px 4px 8px;
	background: var(--surface);
	transition: border-color 0.12s, box-shadow 0.12s;
}
.jvw-input-wrap:focus-within {
	border-color: var(--text);
	box-shadow: 0 0 0 3px rgba(23, 23, 23, 0.07);
}
.jvw-attach {
	flex: none;
	width: 30px;
	height: 30px;
	border-radius: 8px;
	border: none;
	background: transparent;
	color: var(--text-3);
	cursor: pointer;
	display: flex;
	align-items: center;
	justify-content: center;
}
.jvw-attach:hover:not(:disabled) {
	background: var(--surface-2);
	color: var(--text-2);
}
.jvw-input {
	flex: 1;
	resize: none;
	border: none;
	outline: none;
	background: transparent;
	color: var(--text);
	font-family: inherit;
	font-size: 13px;
	line-height: 1.5;
	max-height: 120px;
	padding: 6px 2px;
}
.jvw-input::placeholder {
	color: var(--text-3);
}
.jvw-send {
	flex: none;
	width: 30px;
	height: 30px;
	border-radius: 8px;
	border: none;
	cursor: pointer;
	background: var(--accent);
	display: flex;
	align-items: center;
	justify-content: center;
}
.jvw-send:disabled {
	background: var(--surface-3);
	cursor: default;
}

/* ---- launcher bubble ---- */
.jvw-fab {
	width: 54px;
	height: 54px;
	border-radius: 16px;
	background: var(--accent);
	border: none;
	cursor: pointer;
	display: flex;
	align-items: center;
	justify-content: center;
	box-shadow: 0 6px 20px rgba(23, 23, 23, 0.32);
	position: relative;
	transition: transform 0.15s;
}
.jvw-fab:hover {
	transform: translateY(-1px);
}
.jvw-fab-dot {
	position: absolute;
	top: 6px;
	right: 6px;
	width: 12px;
	height: 12px;
	border-radius: 50%;
	background: var(--green);
	border: 2px solid var(--accent);
}
</style>
