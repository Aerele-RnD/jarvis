<script setup>
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from "vue"
import { useRouter } from "vue-router"
// The desktop SPA's renderer — dependency-free, and sharing it means an agent
// reply reads identically on both surfaces.
import { renderMarkdown } from "@shared/markdown.js"
import * as api from "../api"
import { store } from "../store"

const props = defineProps({ id: { type: String, default: "" } })
const router = useRouter()
const socket = inject("$socket")

// "new" is a route-only placeholder: the conversation does not exist until the
// first send, which is when the backend creates (or focuses) it and tells us
// its real id.
const convId = ref(props.id === "new" ? "" : props.id)
const messages = ref([])
const input = ref("")
const busy = ref(false)
const status = ref("")
const runId = ref(null)
const loading = ref(false)
const scroller = ref(null)
const inputEl = ref(null)

const title = computed(() => {
	const row = store.conversations.find((c) => c.name === convId.value)
	return row?.title || "New chat"
})

function atBottom() {
	const el = scroller.value
	if (!el) return true
	return el.scrollHeight - el.scrollTop - el.clientHeight < 120
}
// Follow the stream only if the user is already at the bottom; yanking them
// down while they scroll back through a long reply is the classic chat sin.
async function scrollToBottom(force = false) {
	const stick = force || atBottom()
	await nextTick()
	if (stick && scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

async function load(force = false) {
	if (!convId.value) return
	loading.value = true
	try {
		const d = await api.getConversation(convId.value)
		messages.value = d?.messages || []
		// A reply still streaming when we (re)opened the chat: restore the spinner
		// from the durable flag rather than assuming the turn is over.
		const last = messages.value[messages.value.length - 1]
		busy.value = !!(last && last.role === "assistant" && last.streaming)
		await scrollToBottom(force)
	} catch (e) {
		console.error("Jarvis PWA: failed to load conversation", e)
	} finally {
		loading.value = false
	}
}

async function send() {
	const text = input.value.trim()
	if (!text || busy.value) return

	input.value = ""
	autoGrow()
	// Optimistic user bubble; the server echoes it back on the next load.
	messages.value.push({ name: `local-${Date.now()}`, role: "user", content: text })
	busy.value = true
	status.value = "Thinking…"
	await scrollToBottom(true)

	try {
		const res = await api.sendMessage(convId.value, text)
		// First send of a brand-new chat: adopt the id the backend just created,
		// and put the row in the list without a refetch.
		const id = res?.conversation_id
		if (id && id !== convId.value) {
			convId.value = id
			router.replace(`/c/${id}`)
			store.loadConversations()
		}
	} catch (e) {
		busy.value = false
		status.value = ""
		messages.value.push({
			name: `err-${Date.now()}`,
			role: "assistant",
			content: "That didn't reach Jarvis. Check your connection and try again.",
			error: 1,
		})
		await scrollToBottom(true)
	}
}

async function stop() {
	if (!convId.value) return
	busy.value = false
	status.value = ""
	try {
		await api.stopRun(convId.value, runId.value)
	} catch {
		// Best-effort: the UI stop stands even if the turn finishes server-side.
	}
}

// The single realtime channel. `assistant:delta` carries the CUMULATIVE text,
// not an increment — assign it, never append, or the reply doubles up.
function onEvent(p) {
	if (p.conversation_id !== convId.value) return

	switch (p.kind) {
		case "run:start":
			runId.value = p.run_id || null
			busy.value = true
			status.value = "Thinking…"
			break
		case "tool:start":
			status.value = p.tool_title || p.tool_name || "Working…"
			break
		case "tool:end":
			status.value = "Thinking…"
			break
		case "run:status":
			if (p.status) status.value = p.status
			break
		case "assistant:delta": {
			const existing = messages.value.find((m) => m.name === p.message_id)
			if (existing) existing.content = p.text
			else messages.value.push({ name: p.message_id, role: "assistant", content: p.text })
			status.value = ""
			scrollToBottom()
			break
		}
		case "run:end":
			busy.value = false
			status.value = ""
			runId.value = null
			// The reply is durable now; reconcile against it (artifacts, final
			// formatting) instead of trusting the streamed copy.
			load()
			break
		case "run:error":
			busy.value = false
			status.value = ""
			messages.value.push({
				name: `err-${Date.now()}`,
				role: "assistant",
				content: p.error || "Something went wrong on that turn.",
				error: 1,
			})
			scrollToBottom()
			break
	}
}

function autoGrow() {
	const el = inputEl.value
	if (!el) return
	el.style.height = "auto"
	el.style.height = `${Math.min(el.scrollHeight, 140)}px`
}

// Enter sends on a physical keyboard; on a phone the on-screen Return key should
// insert a newline, so only intercept when there is no soft keyboard shift key.
function onKeydown(e) {
	if (e.key === "Enter" && !e.shiftKey && !/Mobi|Android/i.test(navigator.userAgent)) {
		e.preventDefault()
		send()
	}
}

const onResync = () => load()

watch(() => props.id, (id) => {
	convId.value = id === "new" ? "" : id
	messages.value = []
	busy.value = false
	load(true)
})

onMounted(() => {
	socket?.on("jarvis:event", onEvent)
	window.addEventListener("jv:resync", onResync)
	if (!store.loaded) store.loadConversations()
	load(true)
})
onUnmounted(() => {
	socket?.off("jarvis:event", onEvent)
	window.removeEventListener("jv:resync", onResync)
})
</script>

<template>
	<div class="jv-bar">
		<button class="jv-icon-btn" aria-label="Back" @click="router.push('/')">
			<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
				<path d="m15 18-6-6 6-6" />
			</svg>
		</button>
		<div class="jv-title">{{ title }}</div>
	</div>

	<div ref="scroller" class="jv-scroll jv-thread">
		<div v-if="!messages.length && !loading" class="jv-empty">
			<div class="jv-mark" style="width: 52px; height: 52px; font-size: 21px">J</div>
			<div style="font-size: 16px; font-weight: 600; color: var(--ink9)">What can I do for you?</div>
			<div style="font-size: 14px; line-height: 1.5">
				Try “show me this month's overdue invoices”.
			</div>
		</div>

		<div v-for="m in messages" :key="m.name" class="jv-msg" :class="m.role">
			<div v-if="m.role === 'user'" class="jv-bubble-user">{{ m.content }}</div>
			<div v-else class="jv-bubble-agent" :class="{ 'is-error': m.error }" v-html="renderMarkdown(m.content || '')" />
		</div>

		<div v-if="busy" class="jv-status">
			<span class="jv-dot" /><span class="jv-dot" /><span class="jv-dot" />
			<span v-if="status" class="jv-status-text">{{ status }}</span>
		</div>
	</div>

	<div class="jv-composer jv-safe-bottom">
		<textarea
			ref="inputEl"
			v-model="input"
			rows="1"
			placeholder="Message Jarvis…"
			@input="autoGrow"
			@keydown="onKeydown"
		/>
		<button v-if="busy" class="jv-send is-stop" aria-label="Stop" @click="stop">
			<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
		</button>
		<button v-else class="jv-send" aria-label="Send" :disabled="!input.trim()" @click="send">
			<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<path d="M12 19V5M5 12l7-7 7 7" />
			</svg>
		</button>
	</div>
</template>

<style scoped>
.jv-thread {
	padding: 14px 12px 8px;
	display: flex;
	flex-direction: column;
	gap: 12px;
}
.jv-msg {
	display: flex;
}
.jv-msg.user {
	justify-content: flex-end;
}
.jv-bubble-user {
	max-width: 82%;
	padding: 10px 14px;
	border-radius: 16px 16px 4px 16px;
	background: var(--accent-solid);
	color: #fff;
	font-size: 15px;
	line-height: 1.5;
	white-space: pre-wrap;
	overflow-wrap: anywhere;
}
.jv-bubble-agent {
	max-width: 92%;
	padding: 11px 14px;
	border-radius: 16px 16px 16px 4px;
	background: var(--card);
	border: 1px solid var(--border);
	color: var(--ink9);
	font-size: 15px;
	line-height: 1.6;
	overflow-wrap: anywhere;
}
.jv-bubble-agent.is-error {
	background: var(--red-bg);
	border-color: transparent;
	color: var(--red);
}
.jv-bubble-agent :deep(p) {
	margin: 0 0 8px;
}
.jv-bubble-agent :deep(p:last-child) {
	margin-bottom: 0;
}
.jv-bubble-agent :deep(pre),
.jv-bubble-agent :deep(table) {
	/* Wide content scrolls inside the bubble; the thread never scrolls sideways. */
	display: block;
	max-width: 100%;
	overflow-x: auto;
}
.jv-bubble-agent :deep(code) {
	font-size: 13px;
	background: var(--card2);
	padding: 1px 5px;
	border-radius: 5px;
}

.jv-status {
	display: flex;
	align-items: center;
	gap: 5px;
	padding: 4px 6px;
}
.jv-dot {
	width: 6px;
	height: 6px;
	border-radius: 50%;
	background: var(--ink4);
	animation: jv-pulse 1.2s infinite ease-in-out;
}
.jv-dot:nth-child(2) {
	animation-delay: 0.15s;
}
.jv-dot:nth-child(3) {
	animation-delay: 0.3s;
}
.jv-status-text {
	margin-left: 6px;
	font-size: 13px;
	color: var(--ink5);
}
@keyframes jv-pulse {
	0%,
	60%,
	100% {
		opacity: 0.3;
	}
	30% {
		opacity: 1;
	}
}

.jv-composer {
	flex: none;
	display: flex;
	align-items: flex-end;
	gap: 8px;
	padding: 10px 12px;
	background: var(--menu-bar);
	border-top: 1px solid var(--border);
}
.jv-composer textarea {
	flex: 1;
	min-width: 0;
	resize: none;
	padding: 11px 14px;
	border: 1px solid var(--border2);
	border-radius: 20px;
	background: var(--card);
	color: var(--ink9);
	font: inherit;
	font-size: 15px;
	line-height: 1.4;
	max-height: 140px;
	outline: none;
}
.jv-composer textarea:focus {
	border-color: var(--accent);
}
.jv-send {
	flex: none;
	width: 40px;
	height: 40px;
	display: grid;
	place-items: center;
	border: 0;
	border-radius: 50%;
	background: var(--accent-solid);
	color: #fff;
	cursor: pointer;
}
.jv-send:disabled {
	background: var(--card3);
	color: var(--ink4);
	cursor: default;
}
.jv-send.is-stop {
	background: var(--ink9);
	color: var(--card);
}
</style>
