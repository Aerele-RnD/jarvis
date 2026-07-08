<template>
	<div class="jv-settings-body">
		<!-- Connection -->
		<div class="jv-set-sec">Connection</div>
		<div class="jv-set-row"><span>Model</span><b>{{ modelLabel }}</b></div>
		<div class="jv-set-row"><span>Provider</span><b>{{ ui.llm_provider || "—" }}</b></div>
		<div class="jv-set-row"><span>Auth mode</span><b>{{ ui.llm_auth_mode || "—" }}</b></div>
		<div class="jv-set-row"><span>Status</span><b :style="{ color: connected ? 'var(--green)' : 'var(--text-3)' }">{{ statusLabel }}</b></div>

		<!-- Behavior -->
		<div class="jv-set-sec" style="margin-top:18px;">Behavior</div>
		<div class="jv-set-row">
			<span>Confirm before changes<br /><span style="font-size:11px;color:var(--text-3);font-weight:400;">Ask before creating, updating, or submitting in this chat. Deletes, cancels, amends, and emails always ask, even with this off.</span></span>
			<button class="jv-switch" :class="{ on: !convAutoApply }" @click="onToggleAutoApply" :disabled="!hasConversation" role="switch" :aria-checked="String(!convAutoApply)" :title="convAutoApply ? 'Auto mode - changes apply without asking' : 'Confirm each change before it runs'">
				<span class="jv-switch-knob"></span>
			</button>
		</div>
		<div v-if="!hasConversation" class="jv-set-row" style="padding-top:0;"><span style="font-size:11px;color:var(--text-3);font-weight:400;">Open a conversation to change this — it's set per chat.</span></div>
		<div v-else-if="autoApplyNote" class="jv-set-row" style="padding-top:0;"><span style="font-size:11px;color:var(--amber);font-weight:500;">{{ autoApplyNote }}</span></div>
		<div class="jv-set-row">
			<span>Show tool activity<br /><span style="font-size:11px;color:var(--text-3);font-weight:400;">Show the live tool steps + input/output above each reply. The tools count &amp; time always show below.</span></span>
			<button class="jv-switch" :class="{ on: showActivityDetail }" @click="setActivityDetail(!showActivityDetail)" role="switch" :aria-checked="String(showActivityDetail)" title="Show the tool/skill activity under each answer">
				<span class="jv-switch-knob"></span>
			</button>
		</div>
		<div class="jv-set-row">
			<span>Notify when a reply is ready<br /><span style="font-size:11px;color:var(--text-3);font-weight:400;">Browser notification when Jarvis finishes while you're in another tab</span></span>
			<button class="jv-switch" :class="{ on: notifyEnabled }" @click="toggleNotify" role="switch" :aria-checked="String(notifyEnabled)" title="Browser notification when a reply finishes in a background tab">
				<span class="jv-switch-knob"></span>
			</button>
		</div>

		<!-- Token usage -->
		<div class="jv-set-sec" style="margin-top:18px;display:flex;align-items:center;gap:7px;">Token usage <span class="jv-est">est.</span></div>
		<div class="jv-set-row"><span>This chat</span><b>{{ usage ? fmtTokens(usage.chat_tokens) : "—" }}</b></div>
		<div class="jv-set-row"><span>{{ usage ? usage.month_label : "This month" }}</span><b>{{ usage ? fmtTokens(usage.month_tokens) : "—" }}</b></div>
		<div class="jv-set-row"><span>All time</span><b>{{ usage ? fmtTokens(usage.total_tokens) : "—" }}</b></div>
		<template v-if="usage && usage.budget_monthly">
			<div class="jv-usage-bar"><div class="jv-usage-fill" :style="{ width: usagePct + '%' }"></div></div>
			<div class="jv-set-hint">{{ fmtTokens(usage.month_tokens) }} / {{ fmtTokens(usage.budget_monthly) }} this month · {{ usagePct }}%</div>
		</template>
		<div v-else class="jv-set-hint">No monthly budget set · counts are estimated from message text.</div>

		<!-- Danger zone -->
		<div class="jv-set-sec" style="margin-top:18px;color:var(--red);">Danger zone</div>
		<div class="jv-set-row">
			<span>Delete all chat history<br /><span style="font-size:11px;color:var(--text-3);font-weight:400;">Every conversation and message, permanently. Macros and skills stay.</span></span>
			<button class="jv-btn jv-btn--sm jv-btn-danger" :disabled="clearing || !canClear" @click="onClearAllHistory">{{ clearing ? "Deleting…" : "Delete all" }}</button>
		</div>
	</div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { useShellStore } from "@/stores/shell"
import * as api from "@/api"

const store = useShellStore()

// Chat-scoped context (null on non-chat routes — guard everything).
const ctx = computed(() => store.chatContext)
const hasConversation = computed(() => !!(ctx.value && ctx.value.conversationId))
const modelLabel = computed(() => (ctx.value && ctx.value.modelLabel) || "Auto")
const ui = computed(() => (ctx.value && ctx.value.ui) || {})
const convAutoApply = computed(() => !!(ctx.value && ctx.value.convAutoApply))
const autoApplyNote = computed(() => (ctx.value && ctx.value.autoApplyNote) || "")

// Real connection status (replaces the old hardcoded "Live"). getLlmConnectionStatus
// is System-Manager-only on the server, and General is an all-user pane — so only
// SM users get the live verdict; regular users (who can't query it and can't fix it
// anyway) keep the benign "Connected" the surface implied before, never a 403 → "—".
const isSM = !!window.is_system_manager
const connStatus = ref(null)
const connected = computed(() =>
	isSM ? !!(connStatus.value && connStatus.value.auth_present) : true,
)
const statusLabel = computed(() => {
	if (!isSM) return "Connected"
	if (!connStatus.value) return "—"
	return connected.value ? "Connected" : "Not connected"
})

// Estimated token usage — the dialog fetches its own data on open.
const usage = ref(null)
const usagePct = computed(() => {
	const u = usage.value
	if (!u || !u.budget_monthly) return 0
	return Math.min(100, Math.round((u.month_tokens / u.budget_monthly) * 100))
})
function fmtTokens(n) {
	n = Number(n || 0)
	if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M"
	if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k"
	return String(n)
}

onMounted(async () => {
	try {
		usage.value = await api.getUsage(ctx.value && ctx.value.conversationId)
	} catch (e) { /* usage is best-effort — leave "—" */ }
	if (isSM) {
		try {
			connStatus.value = await api.getLlmConnectionStatus()
		} catch (e) { /* status stays "—" */ }
	}
})

// Confirm-before-changes → per-conversation action registered by ChatView.
function onToggleAutoApply() {
	const fn = store.settingsActions.toggleAutoApply
	if (typeof fn === "function") fn()
}

// Device-local prefs (localStorage) — mirror ChatView's handlers.
const showActivityDetail = ref(localStorage.getItem("jarvis-activity-detail") === "1")
function setActivityDetail(v) {
	showActivityDetail.value = !!v
	try { localStorage.setItem("jarvis-activity-detail", v ? "1" : "0") } catch (e) {}
}

const notifyEnabled = ref(
	typeof Notification !== "undefined" &&
	localStorage.getItem("jarvis-notify") === "1" &&
	Notification.permission === "granted",
)
async function toggleNotify() {
	if (typeof Notification === "undefined") return
	if (notifyEnabled.value) {
		notifyEnabled.value = false
		try { localStorage.setItem("jarvis-notify", "0") } catch (e) {}
		return
	}
	let perm = Notification.permission
	if (perm !== "granted") {
		try { perm = await Notification.requestPermission() } catch (e) { perm = "denied" }
	}
	if (perm === "granted") {
		notifyEnabled.value = true
		try { localStorage.setItem("jarvis-notify", "1") } catch (e) {}
	}
}

// Delete all history → danger-zone action registered by ChatView.
const clearing = ref(false)
const canClear = computed(() => typeof store.settingsActions.clearAllHistory === "function")
async function onClearAllHistory() {
	const fn = store.settingsActions.clearAllHistory
	if (typeof fn !== "function") return
	clearing.value = true
	try {
		await Promise.resolve(fn())
	} finally {
		clearing.value = false
	}
}
</script>
