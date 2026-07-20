<template>
	<div class="jv-settings-body">
		<template v-if="measured">
			<div class="jv-set-sec">Measured usage</div>
			<div class="jv-set-row"><span>{{ usage.month_label || "This month" }}</span><b>{{ fmtTokens(measured.month_tokens) }}</b></div>
			<div class="jv-set-row"><span>All time</span><b>{{ fmtTokens(measured.total_tokens) }}</b></div>
			<div v-if="measured.last_usage_at" class="jv-set-row"><span>Last activity</span><b>{{ timeAgo(measured.last_usage_at) }}</b></div>
			<template v-if="measured.monthly_token_limit > 0">
				<div class="jv-usage-bar"><div class="jv-usage-fill" :style="{ width: measuredPct + '%' }"></div></div>
				<div class="jv-set-hint">{{ fmtTokens(measured.month_tokens) }} / {{ fmtTokens(measured.monthly_token_limit) }} this month · {{ measuredPct }}%</div>
			</template>
			<div v-else class="jv-set-hint">No monthly limit set on your account.</div>

			<template v-if="perModel.length">
				<div class="jv-set-sec" style="margin-top:20px;">By model · this month</div>
				<div v-for="m in perModel" :key="m.model" class="jv-model-row">
					<div class="jv-model-head">
						<span class="jv-model-name">{{ modelDisplayLabel(m.model) }}</span>
						<span class="jv-model-tok">{{ fmtTokens(m.month_tokens) }}<span class="jv-model-io"> · {{ fmtTokens(m.month_input_tokens) }} in / {{ fmtTokens(m.month_output_tokens) }} out</span></span>
					</div>
					<template v-if="m.monthly_token_limit > 0">
						<div class="jv-usage-bar"><div class="jv-usage-fill" :style="{ width: modelPct(m) + '%' }"></div></div>
						<div class="jv-set-hint">{{ fmtTokens(m.month_tokens) }} / {{ fmtTokens(m.monthly_token_limit) }} · {{ modelPct(m) }}%</div>
					</template>
					<div v-else class="jv-set-hint">unlimited</div>
				</div>
			</template>
		</template>

		<div style="font-size:12px;color:var(--text-3);margin-bottom:14px;" :style="{ marginTop: measured ? '20px' : '0' }">Estimated tokens, messages and tool activity for your workspace. <span class="jv-est">est.</span></div>
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
			<div class="jv-set-sec" style="margin-top:20px;">Tenant monthly budget (informational)</div>
			<div class="jv-usage-bar"><div class="jv-usage-fill" :style="{ width: usagePct + '%' }"></div></div>
			<div class="jv-set-hint">{{ fmtTokens(usage.month_tokens) }} / {{ fmtTokens(usage.budget_monthly) }} this month · {{ usagePct }}%</div>
		</template>
		<div v-else class="jv-set-hint" style="margin-top:14px;">No monthly budget set · token counts are estimated from message text.</div>
	</div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from "vue"
import { useShellStore } from "@/stores/shell"
import { timeAgo } from "@/utils/datetime"
import { modelDisplayLabel } from "@/utils/usageModel"
import * as api from "@/api"

const shell = useShellStore()
const s = computed(() => shell.chatContext?.sessionStats || null)

const usage = ref(null)

// Real (gateway-recorded) usage, added to get_usage()'s response. null until the
// backend ships it or the user has no recorded usage yet (self-hosted stays null).
const measured = computed(() => (usage.value && usage.value.measured) || null)
const measuredPct = computed(() => {
	const m = measured.value
	if (!m || !m.monthly_token_limit) return 0
	return Math.min(100, Math.round((Number(m.month_tokens || 0) / Number(m.monthly_token_limit)) * 100))
})

// Per-model current-month usage + caps (fleet usage spec §7).
const perModel = computed(() => (measured.value && measured.value.per_model) || [])
function modelPct(m) {
	if (!m || !m.monthly_token_limit) return 0
	return Math.min(100, Math.round((Number(m.month_tokens || 0) / Number(m.monthly_token_limit)) * 100))
}

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

<style scoped>
.jv-model-row { margin-top: 12px; }
.jv-model-head { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.jv-model-name { font-size: 13px; font-weight: 600; color: var(--text); }
.jv-model-tok { font-size: 12px; color: var(--text-2); }
.jv-model-io { color: var(--text-3); }
</style>
