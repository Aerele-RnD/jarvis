<template>
	<div class="jv-settings-body">
		<div style="font-size:12px;color:var(--text-3);margin:0 0 14px;">Estimated tokens, messages and tool activity for your workspace. <span class="jv-est">est.</span></div>
		<div class="jv-statgrid">
			<div class="jv-stat"><div class="jv-stat-label">Messages</div><div class="jv-stat-val">{{ s ? s.msgCount : "—" }}</div><div class="jv-stat-sub">{{ s ? `${s.userMsgCount} you · ${s.assistantMsgCount} Jarvis` : "no chat" }}</div></div>
			<div class="jv-stat"><div class="jv-stat-label">Tool calls</div><div class="jv-stat-val">{{ s ? s.sessionToolCalls : "—" }}</div><div class="jv-stat-sub">this session</div></div>
			<div class="jv-stat"><div class="jv-stat-label">Avg tokens / msg</div><div class="jv-stat-val">{{ s ? s.avgTokensPerMsg : "—" }}</div><div class="jv-stat-sub">this chat</div></div>
			<div class="jv-stat"><div class="jv-stat-label">Conversations</div><div class="jv-stat-val">{{ s ? s.convCount : "—" }}</div><div class="jv-stat-sub">{{ s ? `${s.starredCount} starred` : "no chat" }}</div></div>
			<div class="jv-stat"><div class="jv-stat-label">This chat</div><div class="jv-stat-val">{{ usage ? fmtTokens(usage.chat_tokens) : "—" }}</div><div class="jv-stat-sub">tokens</div></div>
			<div class="jv-stat"><div class="jv-stat-label">{{ usage ? usage.month_label : "This month" }}</div><div class="jv-stat-val">{{ usage ? fmtTokens(usage.month_tokens) : "—" }}</div><div class="jv-stat-sub">tokens</div></div>
			<div class="jv-stat"><div class="jv-stat-label">All time</div><div class="jv-stat-val">{{ usage ? fmtTokens(usage.total_tokens) : "—" }}</div><div class="jv-stat-sub">tokens</div></div>
			<div class="jv-stat"><div class="jv-stat-label">Tools</div><div class="jv-stat-val">{{ s ? s.toolCount : "—" }}</div><div class="jv-stat-sub">available</div></div>
		</div>
		<template v-if="usage && usage.budget_monthly">
			<div class="jv-set-sec" style="margin-top:20px;">Monthly budget</div>
			<div class="jv-usage-bar"><div class="jv-usage-fill" :style="{ width: usagePct + '%' }"></div></div>
			<div class="jv-set-hint">{{ fmtTokens(usage.month_tokens) }} / {{ fmtTokens(usage.budget_monthly) }} this month · {{ usagePct }}%</div>
		</template>
		<div v-else class="jv-set-hint" style="margin-top:14px;">No monthly budget set · token counts are estimated from message text.</div>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from "vue"
import { useShellStore } from "@/stores/shell"
import * as api from "@/api"

const shell = useShellStore()
const s = computed(() => shell.chatContext?.sessionStats || null)

const usage = ref(null)

async function loadUsage() {
	try {
		usage.value = await api.getUsage(shell.chatContext?.conversationId)
	} catch {
		usage.value = null
	}
}

function fmtTokens(n) {
	n = Number(n || 0)
	if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M"
	if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k"
	return String(n)
}

const usagePct = computed(() => {
	const u = usage.value
	if (!u || !u.budget_monthly) return 0
	return Math.min(100, Math.round((u.month_tokens / u.budget_monthly) * 100))
})

onMounted(loadUsage)
watch(() => shell.chatContext?.conversationId, loadUsage)
</script>
