<template>
	<div class="jv-settings-body">
		<div class="jv-statgrid">
			<div class="jv-stat"><div class="jv-stat-label">Total runs</div><div class="jv-stat-val">{{ macroRunStats ? macroRunStats.total : "—" }}</div><div class="jv-stat-sub">all time</div></div>
			<div class="jv-stat"><div class="jv-stat-label">Success rate</div><div class="jv-stat-val" style="color:var(--green);">{{ macroRunStats && macroRunStats.success_rate != null ? macroRunStats.success_rate + "%" : "—" }}</div><div class="jv-stat-sub">completed ÷ finished</div></div>
			<div class="jv-stat"><div class="jv-stat-label">Running now</div><div class="jv-stat-val" style="color:var(--cta);">{{ macroRunStats ? macroRunStats.running : "—" }}</div><div class="jv-stat-sub">active</div></div>
			<div class="jv-stat"><div class="jv-stat-label">Last run</div><div class="jv-stat-val">{{ macroRunStats && macroRunStats.last_run_at ? fmtAgo(macroRunStats.last_run_at) : "—" }}</div><div class="jv-stat-sub">&nbsp;</div></div>
		</div>
		<div class="jv-runfilters">
			<div class="jv-seg jv-runchips">
				<button v-for="s in MACRO_RUN_STATUSES" :key="s || 'all'" :class="{ on: macroRunStatus === s }" @click="setMacroRunStatus(s)">{{ s ? (s[0].toUpperCase() + s.slice(1)) : "All" }}</button>
			</div>
			<select class="jv-runmacrosel" :value="macroRunMacro" @change="setMacroRunMacro">
				<option value="">All macros</option>
				<option v-for="mm in macros" :key="mm.name" :value="mm.name">{{ mm.macro_name }}</option>
			</select>
		</div>
		<div v-if="!macroRuns.length && !macroRunsLoading" class="jv-set-empty" style="text-align:center;padding:30px 0;">No macro runs yet.<br />Run a macro to see its history here.</div>
		<div v-for="run in macroRuns" :key="run.name" class="jv-run">
			<span class="jv-run-dot" :class="'d-' + macroRunBadge(run.status)"></span>
			<div class="jv-run-main">
				<div class="jv-run-top">
					<span class="jv-run-name">{{ run.macro_name }}</span>
					<span class="jv-run-badge" :class="'b-' + macroRunBadge(run.status)">{{ run.status }}</span>
					<span class="jv-run-trig">
						<svg v-if="run.trigger === 'scheduled'" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="5" width="16" height="15" rx="2" /><path d="M8 3v4M16 3v4M4 10h16" /></svg>
						<svg v-else width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v4l3 2" /></svg>
						{{ run.trigger }}
					</span>
				</div>
				<div class="jv-run-meta">
					<span class="jv-run-prog">{{ run.current_step }}/{{ run.total_steps }}</span>
					<span class="jv-run-sep">·</span><span>{{ fmtAgo(run.started_at || run.creation) }}</span>
					<template v-if="macroRunElapsed(run)"><span class="jv-run-sep">·</span><span>{{ macroRunElapsed(run) }}</span></template>
				</div>
				<div v-if="run.error" class="jv-run-err">
					<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></svg>
					{{ run.error }}
				</div>
			</div>
			<div class="jv-run-act">
				<button v-if="run.status === 'running' || run.status === 'queued'" class="jv-run-btn stop" @click="stopRunFromHistory(run)">Stop</button>
				<button v-else class="jv-run-btn" @click="rerunFromHistory(run)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v6h6M21 12a9 9 0 1 1-3-6.7L21 8" /></svg>Re-run</button>
				<button v-if="run.conversation" class="jv-run-btn" @click="openRunConversation(run)">Open ›</button>
			</div>
		</div>
		<button v-if="macroRunHasMore" class="jv-run-loadmore" :disabled="macroRunsLoading" @click="loadMacroRuns(false)">{{ macroRunsLoading ? "Loading…" : "Load more" }}</button>
	</div>
</template>

<script setup>
import { ref, inject, onMounted, onBeforeUnmount } from "vue"
import { useRouter } from "vue-router"
import { toast } from "frappe-ui"
import { useShellStore } from "@/stores/shell"
import * as api from "@/api"

const store = useShellStore()
const router = useRouter()
const socket = inject("$socket")

// --- Macros (populate the macro filter dropdown) ---
const macros = ref([])
async function loadMacros() {
	try { macros.value = (await api.listMacros()) || [] } catch (e) { /* keep prior */ }
}

// ---- Macro run history dashboard ----
const MACRO_RUN_PAGE = 30
const macroRuns = ref([])
const macroRunStats = ref(null)
const macroRunStatus = ref("") // "" = all
const macroRunMacro = ref("") // "" = all macros
const macroRunStart = ref(0)
const macroRunHasMore = ref(false)
const macroRunsLoading = ref(false)
const MACRO_RUN_STATUSES = ["", "running", "completed", "failed", "stopped"]

async function loadMacroRunStats() {
	try { macroRunStats.value = await api.macroRunStats() } catch (e) { /* keep prior */ }
}
// reset=true starts a fresh page-1 load (also refreshes stats + the macro
// filter options); reset=false appends the next page ("Load more").
async function loadMacroRuns(reset = true) {
	if (macroRunsLoading.value) return
	macroRunsLoading.value = true
	if (reset) {
		macroRunStart.value = 0
		loadMacroRunStats()
		if (!macros.value.length) loadMacros() // populate the macro filter dropdown
	}
	try {
		const r = await api.listMacroRuns({
			status: macroRunStatus.value,
			macro: macroRunMacro.value,
			limit: MACRO_RUN_PAGE,
			start: macroRunStart.value,
		})
		const rows = (r && r.runs) || []
		macroRuns.value = reset ? rows : [...macroRuns.value, ...rows]
		macroRunHasMore.value = !!(r && r.has_more)
		macroRunStart.value += rows.length
	} catch (e) { /* keep the last-good list */ } finally { macroRunsLoading.value = false }
}
function setMacroRunStatus(s) { macroRunStatus.value = s; loadMacroRuns(true) }
function setMacroRunMacro(e) { macroRunMacro.value = e.target.value; loadMacroRuns(true) }

// Row actions -------------------------------------------------------------
function openRunConversation(run) {
	if (!run.conversation) return
	store.settingsOpen = false
	router.push({ name: "Conversation", params: { id: run.conversation } })
}
async function rerunFromHistory(run) {
	try {
		const res = await api.runMacro(run.macro)
		const data = (res && res.data) || res || {}
		store.settingsOpen = false
		if (data.conversation) router.push({ name: "Conversation", params: { id: data.conversation } })
	} catch (e) { toast.error(_skillErr(e)) }
}
async function stopRunFromHistory(run) {
	try {
		await api.stopMacroRun(run.name)
		run.status = "stopped" // optimistic patch
		loadMacroRunStats()
	} catch (e) { toast.error(_skillErr(e)) }
}

// Formatters --------------------------------------------------------------
function _skillErr(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}
function macroRunBadge(status) {
	return { completed: "ok", failed: "err", running: "run", queued: "run", stopped: "stop" }[status] || "stop"
}
function fmtAgo(dt) {
	if (!dt) return ""
	const t = new Date(String(dt).replace(" ", "T")).getTime()
	if (isNaN(t)) return ""
	const s = Math.max(0, Math.floor((Date.now() - t) / 1000))
	if (s < 60) return "just now"
	const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`
	const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`
	const d = Math.floor(h / 24); if (d < 7) return `${d}d ago`
	return new Date(t).toLocaleDateString()
}
function fmtDuration(sec) {
	if (sec == null) return ""
	sec = Math.max(0, Math.round(sec))
	if (sec < 60) return `${sec}s`
	const m = Math.floor(sec / 60), s = sec % 60
	if (m < 60) return s ? `${m}m ${s}s` : `${m}m`
	const h = Math.floor(m / 60)
	return `${h}h ${m % 60}m`
}
// Elapsed for a run that hasn't finished (running/queued) — shows "· 18s".
function macroRunElapsed(run) {
	if (run.duration_s != null || !run.started_at) return fmtDuration(run.duration_s)
	const t = new Date(String(run.started_at).replace(" ", "T")).getTime()
	if (isNaN(t)) return ""
	return fmtDuration((Date.now() - t) / 1000) + " elapsed"
}

// Live updates ------------------------------------------------------------
// Live-patch the open dashboard from macro:progress / macro:done events.
function patchMacroRunRow(p, done) {
	const row = macroRuns.value.find((r) => r.name === p.macro_run)
	if (row) {
		if (p.step != null) row.current_step = p.step
		row.status = done ? (p.status || "completed") : "running"
	}
	loadMacroRunStats()
}
function onEvent(p) {
	if (p.kind === "macro:progress") { patchMacroRunRow(p, false); return }
	if (p.kind === "macro:done") { patchMacroRunRow(p, true); return }
}

onMounted(() => {
	loadMacroRuns(true) // fresh load whenever the pane opens
	socket && socket.on && socket.on("jarvis:event", onEvent)
})
onBeforeUnmount(() => {
	socket && socket.off && socket.off("jarvis:event", onEvent)
})
</script>
