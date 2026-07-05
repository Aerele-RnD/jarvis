<template>
	<PageShell crumb="Macros" title="Macros"
		subtitle="Saved prompt sequences your assistant runs as a chain of turns."
		:tabs="tabs" base-path="/macros" default-tab="macros"
		v-model="activeTab" @esc="onEsc">
		<template #actions>
			<button v-if="activeTab === 'macros'" class="fp-btn fp-btn--primary fp-btn--sm" @click="newMacro">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg> New
			</button>
		</template>

		<!-- ============ MACROS TAB ============ -->
		<FeatureListPage v-if="activeTab === 'macros'" ref="flpRef"
			:columns="columns"
			:fetch-fn="fetchMacros"
			:filters-config="filtersConfig"
			:search-config="{ placeholder: 'Search macros', debounceMs: 300 }"
			:sortable-keys="['macro_name', 'last_run_at', 'next_run_at']"
			:default-sort="{ field: 'macro_name', dir: 'asc' }"
			:row-actions="rowActions"
			:on-row-click="editMacro"
			:empty-state="{ title: 'No macros yet.', description: 'Hit New to record a sequence of prompts.' }">
			<template #cell-macro_name="{ row }">
				<span class="mv-name">{{ row.macro_name }}</span>
				<span v-if="!row.enabled" class="fp-chip fp-chip--muted">draft</span>
			</template>
			<template #cell-summary="{ row }">
				<span v-if="row.merge_status === 'pending'" class="fp-chip fp-chip--amber" title="Summarizing in the background">summarizing…</span>
				<span v-else-if="row.has_summary" class="fp-chip fp-chip--green" title="Runs its summarized prompt as one turn">summary</span>
				<span v-else class="mv-dash">—</span>
			</template>
			<template #cell-schedule="{ row }">
				<span v-if="row.schedule_enabled" class="fp-chip fp-chip--blue">
					{{ (row.schedule_frequency || "scheduled") }}<span v-if="row.schedule_time"> · {{ row.schedule_time }}</span>
				</span>
				<span v-else class="mv-dash">—</span>
			</template>
		</FeatureListPage>

		<!-- ============ RUNS TAB (Settings→Macro-runs dashboard, ported) ============ -->
		<div v-else-if="activeTab === 'runs'" class="mv-runs">
			<div class="jv-statgrid">
				<div class="jv-stat"><div class="jv-stat-label">Total runs</div><div class="jv-stat-val">{{ macroRunStats ? macroRunStats.total : "—" }}</div><div class="jv-stat-sub">all time</div></div>
				<div class="jv-stat"><div class="jv-stat-label">Success rate</div><div class="jv-stat-val" style="color:var(--green);">{{ macroRunStats && macroRunStats.success_rate != null ? macroRunStats.success_rate + "%" : "—" }}</div><div class="jv-stat-sub">completed ÷ finished</div></div>
				<div class="jv-stat"><div class="jv-stat-label">Running now</div><div class="jv-stat-val" style="color:var(--blue);">{{ macroRunStats ? macroRunStats.running : "—" }}</div><div class="jv-stat-sub">active</div></div>
				<div class="jv-stat"><div class="jv-stat-label">Last run</div><div class="jv-stat-val">{{ macroRunStats && macroRunStats.last_run_at ? fmtAgo(macroRunStats.last_run_at) : "—" }}</div><div class="jv-stat-sub">&nbsp;</div></div>
			</div>
			<div class="jv-runfilters">
				<div class="jv-runchips">
					<button v-for="s in MACRO_RUN_STATUSES" :key="s || 'all'" :class="{ on: macroRunStatus === s }" @click="setMacroRunStatus(s)">{{ s ? (s[0].toUpperCase() + s.slice(1)) : "All" }}</button>
				</div>
				<select class="jv-runmacrosel" :value="macroRunMacro" @change="setMacroRunMacro">
					<option value="">All macros</option>
					<option v-for="mm in macrosList" :key="mm.name" :value="mm.name">{{ mm.macro_name }}</option>
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

		<!-- ============ MACRO EDITOR DRAWER (720px) ============ -->
		<JvDrawer v-model="editorOpen" :width="720"
			:title="macroForm.name ? 'Edit macro' : 'New macro'"
			subtitle="Each step runs as its own agent turn, in order.">
			<label class="jv-skill-l">Name</label>
			<input class="jv-skill-in" v-model="macroForm.macro_name" placeholder="e.g. Monthly close" maxlength="140" />
			<div style="height:10px;"></div>
			<label class="jv-skill-l">Description</label>
			<input class="jv-skill-in" v-model="macroForm.description" placeholder="What does this macro do?" maxlength="500" />
			<div class="jv-set-row" style="margin-top:12px;"><span>Stop if a step fails<br /><span class="mv-sub">Otherwise the chain keeps going after an error</span></span><button class="fp-switch" :class="{ on: macroForm.stop_on_error }" @click="macroForm.stop_on_error = !macroForm.stop_on_error" role="switch" :aria-checked="String(!!macroForm.stop_on_error)"><span class="fp-switch-knob"></span></button></div>
			<div class="jv-set-row"><span>Run on a schedule<br /><span class="mv-sub">Jarvis runs this macro automatically</span></span><button class="fp-switch" :class="{ on: macroForm.schedule_enabled }" @click="macroForm.schedule_enabled = !macroForm.schedule_enabled" role="switch" :aria-checked="String(!!macroForm.schedule_enabled)"><span class="fp-switch-knob"></span></button></div>
			<div v-if="macroForm.schedule_enabled" class="jv-macro-sched-fields">
				<div style="flex:1;">
					<label class="jv-skill-l">Frequency</label>
					<select class="jv-skill-in" v-model="macroForm.schedule_frequency"><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select>
				</div>
				<div style="flex:1;">
					<label class="jv-skill-l">Time</label>
					<input type="time" class="jv-skill-in" v-model="macroForm.schedule_time" />
				</div>
			</div>
			<!-- Steps stay the editable source; the summarized prompt (own tab) is what runs when set. -->
			<div class="jv-macro-tabs">
				<button class="jv-macro-tab" :class="{ on: macroEdTab === 'steps' }" @click="macroEdTab = 'steps'">Steps</button>
				<button class="jv-macro-tab" :class="{ on: macroEdTab === 'summary' }" @click="macroEdTab = 'summary'">
					Summarized prompt<span v-if="(macroForm.merged_prompt || '').trim()" class="jv-macro-tab-dot" title="A summary is set — it runs instead of the steps"></span>
				</button>
			</div>
			<template v-if="macroEdTab === 'summary'">
				<template v-if="(macroForm.merged_prompt || '').trim()">
					<div class="jv-merge-sub" style="margin-top:10px;">This single prompt <b>runs when you hit Run</b> — the steps stay as its source. Edit freely; saving keeps your edit.</div>
					<textarea class="jv-merge-text" style="margin-top:8px;" v-model="macroForm.merged_prompt" rows="9"></textarea>
					<button class="jv-skill-newrow" style="margin-top:10px;margin-bottom:0;" @click="macroForm.merged_prompt = ''">✕ Remove summary — run the steps instead</button>
				</template>
				<div v-else class="jv-set-empty" style="margin-top:12px;">No summary yet. Saving with 2+ steps generates one automatically in the background — it lands here and becomes what runs (Run stays locked until it's ready).</div>
			</template>
			<template v-if="macroEdTab === 'steps'">
				<div v-if="!macroForm.steps.length" class="jv-set-empty">No steps yet. Add one below.</div>
				<div v-for="(st, si) in macroForm.steps" :key="si" class="jv-macro-step" :class="{ dragging: dragStepIdx === si, dragover: dragOverIdx === si && dragStepIdx !== null && dragStepIdx !== si }" @dragover.prevent="onStepDragOver(si)" @dragleave="onStepDragLeave(si)" @drop.prevent="onStepDrop(si)">
					<div class="jv-macro-step-head">
						<span class="jv-macro-grip" draggable="true" title="Drag to reorder" @dragstart="onStepDragStart(si, $event)" @dragend="onStepDragEnd"><svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.5" /><circle cx="15" cy="6" r="1.5" /><circle cx="9" cy="12" r="1.5" /><circle cx="15" cy="12" r="1.5" /><circle cx="9" cy="18" r="1.5" /><circle cx="15" cy="18" r="1.5" /></svg></span>
						<span class="jv-macro-step-num">{{ si + 1 }}</span>
						<input class="jv-skill-in jv-macro-step-label" v-model="st.label" placeholder="Optional label" maxlength="140" />
						<button class="fp-iconbtn danger" title="Remove step" @click="removeMacroStep(si)"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg></button>
					</div>
					<textarea class="jv-skill-ta" v-model="st.prompt" rows="3" placeholder="The prompt to send for this step…"></textarea>
					<div v-if="macroSkillOptions.length" class="jv-macro-step-skills">
						<span class="jv-macro-step-skills-l"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z" /></svg>Skills</span>
						<button v-for="s in macroSkillOptions" :key="s.name" class="jv-macro-skill-opt jv-macro-skill-opt--sm" :class="{ on: (st.skills || []).includes(s.name) }" @click="toggleStepSkill(si, s.name)" :title="s.description || s.skill_name">
							<span v-if="(st.skills || []).includes(s.name)" class="jv-ask-tick">✓</span>/{{ s.skill_name }}<span v-if="!s.mine" class="jv-macro-skill-shared">shared</span>
						</button>
					</div>
				</div>
				<button class="jv-skill-newrow" style="margin-top:12px;margin-bottom:0;" @click="addMacroStep"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg> Add step</button>
			</template>
			<!-- Error sits next to Save (the body scrolls; a top-of-form message is off-screen with a long step list). -->
			<div v-if="macroError" class="jv-skill-err" style="margin-top:12px;">{{ macroError }}</div>

			<template #footer>
				<button class="fp-btn fp-btn--primary" :disabled="macroSaving" @click="saveMacro">{{ macroSaving ? "Saving…" : "Save macro" }}</button>
				<button class="fp-btn fp-btn--ghost" :disabled="macroSaving" @click="editorOpen = false">Cancel</button>
			</template>
		</JvDrawer>
	</PageShell>
</template>

<script setup>
import { ref, computed, inject, watch, onMounted, onBeforeUnmount } from "vue"
import { useRouter } from "vue-router"
import PageShell from "@/components/PageShell.vue"
import FeatureListPage from "@/components/FeatureListPage.vue"
import JvDrawer from "@/components/JvDrawer.vue"
import { useNotify } from "@/composables/useNotify"
import { takeMacroPrefill } from "@/composables/macroPrefill"
import * as api from "@/api"

const router = useRouter()
const socket = inject("$socket")
const { notify, confirmDialog, errMsg } = useNotify()

const tabs = [{ id: "macros", label: "Macros" }, { id: "runs", label: "Runs" }]
const activeTab = ref("macros")

// ── macros list config ───────────────────────────────────────────────────────
const flpRef = ref(null)
const fetchMacros = (p) => api.listMacrosPage(p)
const columns = [
	{ key: "macro_name", label: "Macro", width: 1.4 },
	{ key: "step_count", label: "Steps", width: 0.5, align: "center", format: (v) => (v || 0) },
	{ key: "summary", label: "Summary", width: 0.8 },
	{ key: "schedule", label: "Schedule", width: 0.9 },
	{ key: "last_run_at", label: "Last run", width: 0.8, format: (v) => fmtAgo(v) || "—" },
	{ key: "next_run_at", label: "Next run", width: 0.9, format: (v) => fmtWhen(v) },
]
const filtersConfig = [
	{ key: "enabled", label: "Status", type: "select", default: "", options: [
		{ label: "All", value: "" }, { label: "Enabled", value: 1 }, { label: "Draft", value: 0 } ] },
	{ key: "schedule_enabled", label: "Schedule", type: "select", default: "", options: [
		{ label: "All", value: "" }, { label: "Scheduled", value: 1 }, { label: "Manual", value: 0 } ] },
	{ key: "schedule_frequency", label: "Frequency", type: "select", default: "", options: [
		{ label: "All freq", value: "" }, { label: "Daily", value: "daily" }, { label: "Weekly", value: "weekly" }, { label: "Monthly", value: "monthly" } ] },
]

const ICON_PLAY = '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4l14 8-14 8V4z"/></svg>'
const ICON_HOURGLASS = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
const ICON_EDIT = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>'
const ICON_TRASH = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>'

function rowActions(row) {
	const acts = []
	if (row.merge_status === "pending") {
		// Run is gated while the summary is being prepared (ChatView.vue:799). The
		// visible "summarizing…" state shows in the Summary column chip; the Run
		// action is a disabled clock with the explanatory tooltip.
		acts.push({ id: "run", label: "Summarizing…", icon: ICON_HOURGLASS, disabled: true, title: "Summarizing… — Run unlocks when the summary is ready", onClick: () => {} })
	} else {
		acts.push({ id: "run", label: "Run", icon: ICON_PLAY, title: "Run", onClick: runMacroRow })
	}
	acts.push({ id: "edit", label: "Edit", icon: ICON_EDIT, title: "Edit", onClick: editMacro })
	acts.push({ id: "delete", label: "Delete", icon: ICON_TRASH, danger: true, title: "Delete", onClick: removeMacro })
	return acts
}

async function runMacroRow(row) {
	try {
		const res = await api.runMacro(row.name)
		const data = (res && res.data) || res || {}
		// Hand off to the chat: the live macro banner is ChatView's own machinery.
		if (data.conversation) router.push("/c/" + data.conversation)
	} catch (e) { notify(errMsg(e), { type: "error" }) }
}
async function removeMacro(row) {
	if (!(await confirmDialog({ title: "Delete macro?", message: `Delete “${row.macro_name}”? This can't be undone.`, confirmLabel: "Delete" }))) return
	try {
		await api.deleteMacro(row.name)
		flpRef.value && flpRef.value.refresh()
		notify("Macro deleted", { type: "success" })
	} catch (e) { notify(errMsg(e), { type: "error" }) }
}

// ── editor drawer ────────────────────────────────────────────────────────────
const editorOpen = ref(false)
const macroSaving = ref(false)
const macroError = ref("")
const macroEdTab = ref("steps") // "steps" | "summary"
const macroForm = ref(_blankMacro())
const macroSkillOptions = ref([]) // own + shared-with-me, enabled only

function _blankMacro() {
	return {
		name: "", macro_name: "", description: "",
		enabled: true, stop_on_error: true,
		schedule_enabled: false, schedule_frequency: "daily", schedule_time: "09:00",
		steps: [],
		// _orig* snapshots let saveMacro tell "steps changed → stale summary" from a rename-only save.
		merged_prompt: "", _origMerged: "", _origStepsJson: "",
	}
}
async function loadSkillOptions() {
	// Taggable on a step: own + shared-with-me, enabled only (a disabled skill can't be invoked).
	try {
		const all = (await api.listCustomSkills()) || []
		macroSkillOptions.value = all.filter((s) => s.enabled)
	} catch (e) { /* keep prior */ }
}
function newMacro() {
	macroError.value = ""
	macroForm.value = _blankMacro()
	macroForm.value.steps = [{ label: "", prompt: "", skills: [] }]
	macroEdTab.value = "steps"
	loadSkillOptions()
	editorOpen.value = true
}
async function editMacro(m) {
	macroError.value = ""
	try {
		const full = await api.getMacro(m.name)
		const steps = (Array.isArray(full.steps) ? full.steps : []).map((s) => ({ label: s.label || "", prompt: s.prompt || "", skills: Array.isArray(s.skills) ? [...s.skills] : [] }))
		macroForm.value = {
			name: full.name,
			macro_name: full.macro_name || "",
			description: full.description || "",
			enabled: full.enabled == null ? true : !!full.enabled,
			stop_on_error: !!full.stop_on_error,
			schedule_enabled: !!full.schedule_enabled,
			schedule_frequency: full.schedule_frequency || "daily",
			schedule_time: full.schedule_time || "09:00",
			steps,
			merged_prompt: full.merged_prompt || "",
			_origMerged: full.merged_prompt || "",
			_origStepsJson: JSON.stringify(steps.filter((s) => (s.prompt || "").trim())),
		}
		if (!macroForm.value.steps.length) macroForm.value.steps = [{ label: "", prompt: "", skills: [] }]
		macroEdTab.value = "steps"
		loadSkillOptions()
		editorOpen.value = true
	} catch (e) { notify(errMsg(e), { type: "error" }) }
}
function addMacroStep() { macroForm.value.steps.push({ label: "", prompt: "", skills: [] }) }
function removeMacroStep(i) { macroForm.value.steps.splice(i, 1) }
function toggleStepSkill(si, name) {
	const st = macroForm.value.steps[si]
	if (!st) return
	if (!Array.isArray(st.skills)) st.skills = []
	const i = st.skills.indexOf(name)
	if (i >= 0) st.skills.splice(i, 1)
	else st.skills.push(name)
}
// Drag-to-reorder steps (grip is the source; the whole card is the drop target).
const dragStepIdx = ref(null)
const dragOverIdx = ref(null)
function onStepDragStart(i, e) {
	dragStepIdx.value = i
	if (e && e.dataTransfer) {
		e.dataTransfer.effectAllowed = "move"
		try { e.dataTransfer.setData("text/plain", String(i)) } catch (_) { /* ignore */ }
	}
}
function onStepDragOver(i) { if (dragStepIdx.value !== null) dragOverIdx.value = i }
function onStepDragLeave(i) { if (dragOverIdx.value === i) dragOverIdx.value = null }
function onStepDrop(i) {
	const from = dragStepIdx.value
	dragOverIdx.value = null
	if (from === null || from === i) { dragStepIdx.value = null; return }
	const steps = macroForm.value.steps
	const [it] = steps.splice(from, 1)
	steps.splice(i, 0, it)
	dragStepIdx.value = null
}
function onStepDragEnd() { dragStepIdx.value = null; dragOverIdx.value = null }

// Save semantics EXACTLY as ChatView.vue:1926-1971.
async function saveMacro() {
	macroError.value = ""
	const f = macroForm.value
	const steps = f.steps
		.map((s) => ({ label: (s.label || "").trim(), prompt: (s.prompt || "").trim(), skills: Array.isArray(s.skills) ? s.skills : [] }))
		.filter((s) => s.prompt)
	if (!(f.macro_name || "").trim()) { macroError.value = "Give the macro a name."; return }
	if (!steps.length) { macroError.value = "Add at least one step with a prompt."; return }
	macroSaving.value = true
	try {
		const payload = {
			macro_name: f.macro_name.trim(),
			description: f.description || "",
			steps,
			enabled: f.enabled ? 1 : 0,
			stop_on_error: f.stop_on_error ? 1 : 0,
			schedule_enabled: f.schedule_enabled ? 1 : 0,
			schedule_frequency: f.schedule_frequency || "daily",
			schedule_time: f.schedule_time || "09:00",
		}
		// Summary handling (update only): an edited summary is explicit intent → send it;
		// a rename-only save keeps the stored one; changed steps with an untouched summary
		// omit it → the backend clears the stale copy and the re-summarize regenerates it.
		const stepsTouched = JSON.stringify(steps) !== (f._origStepsJson || "")
		const mergedTouched = (f.merged_prompt || "") !== (f._origMerged || "")
		let sentMerged = ""
		let savedName = f.name
		if (f.name) {
			const upd = { name: f.name, ...payload }
			if (mergedTouched || !stepsTouched) {
				upd.merged_prompt = (f.merged_prompt || "").trim()
				sentMerged = upd.merged_prompt
			}
			await api.updateMacro(upd)
		} else {
			const r = await api.createMacro(payload)
			savedName = r && r.data && r.data.name
		}
		editorOpen.value = false
		flpRef.value && flpRef.value.refresh()
		// Re-summarize only when the sequence actually changed (or has no summary yet)
		// — a rename shouldn't burn an LLM turn.
		const needsSummary = steps.length >= 2 && (stepsTouched || !f.name || !sentMerged)
		if (savedName && needsSummary) startMacroMerge(savedName)
	} catch (e) { macroError.value = errMsg(e) } finally { macroSaving.value = false }
}
async function startMacroMerge(name) {
	try {
		await api.summarizeMacro(name)
		notify("Summarizing in the background — Run unlocks when the summary is ready.", { type: "info" })
	} catch (e) { /* macro is saved either way; without a summary the steps run */ }
	flpRef.value && flpRef.value.refresh() // pick up merge_status=pending for the Run gate
}

// ── runs dashboard (Settings→Macro-runs, ported) ─────────────────────────────
const MACRO_RUN_PAGE = 30
const MACRO_RUN_STATUSES = ["", "running", "completed", "failed", "stopped"]
const macroRuns = ref([])
const macroRunStats = ref(null)
const macroRunStatus = ref("")
const macroRunMacro = ref("")
const macroRunStart = ref(0)
const macroRunHasMore = ref(false)
const macroRunsLoading = ref(false)
const macrosList = ref([]) // macro filter dropdown (list_macros)

async function loadMacroRunStats() {
	try { macroRunStats.value = await api.macroRunStats() } catch (e) { /* keep prior */ }
}
async function loadMacrosList() {
	try { macrosList.value = (await api.listMacros()) || [] } catch (e) { /* keep prior */ }
}
// reset=true starts a fresh page-1 load (+ stats + macro filter options); reset=false appends.
async function loadMacroRuns(reset = true) {
	if (macroRunsLoading.value) return
	macroRunsLoading.value = true
	if (reset) {
		macroRunStart.value = 0
		loadMacroRunStats()
		if (!macrosList.value.length) loadMacrosList()
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
async function openRunConversation(run) { if (run.conversation) router.push("/c/" + run.conversation) }
async function rerunFromHistory(run) {
	try {
		const res = await api.runMacro(run.macro)
		const data = (res && res.data) || res || {}
		if (data.conversation) router.push("/c/" + data.conversation)
	} catch (e) { notify(errMsg(e), { type: "error" }) }
}
async function stopRunFromHistory(run) {
	try {
		await api.stopMacroRun(run.name)
		run.status = "stopped" // optimistic patch
		loadMacroRunStats()
	} catch (e) { notify(errMsg(e), { type: "error" }) }
}

// ── formatters (ported from ChatView) ────────────────────────────────────────
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
function fmtWhen(dt) {
	if (!dt) return "—"
	const t = new Date(String(dt).replace(" ", "T")).getTime()
	if (isNaN(t)) return "—"
	return new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
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
function macroRunElapsed(run) {
	if (run.duration_s != null || !run.started_at) return fmtDuration(run.duration_s)
	const t = new Date(String(run.started_at).replace(" ", "T")).getTime()
	if (isNaN(t)) return ""
	return fmtDuration((Date.now() - t) / 1000) + " elapsed"
}

// ── socket: macro:merged (refresh + notice), macro:progress|done (live-patch runs) ──
function patchMacroRunRow(p, done) {
	if (activeTab.value !== "runs") return
	const row = macroRuns.value.find((r) => r.name === p.macro_run)
	if (row) {
		if (p.step != null) row.current_step = p.step
		row.status = done ? (p.status || "completed") : "running"
	}
	loadMacroRunStats()
}
function onEvent(p) {
	if (!p || !p.kind) return
	if (p.kind === "macro:merged") {
		flpRef.value && flpRef.value.refresh({ keepPage: true })
		notify(
			p.status === "ready"
				? `Summary ready — “${p.macro_name || "macro"}” now runs as one prompt.`
				: `“${p.macro_name || "Macro"}” keeps its step sequence (couldn't summarize).`,
			{ type: p.status === "ready" ? "success" : "info" },
		)
		return
	}
	if (p.kind === "macro:progress") { patchMacroRunRow(p, false); return }
	if (p.kind === "macro:done") { patchMacroRunRow(p, true); return }
}

function onEsc() { if (editorOpen.value) editorOpen.value = false }

// Load the runs dashboard when its tab becomes active (fresh each time, like ChatView).
watch(activeTab, (t) => { if (t === "runs") loadMacroRuns(true) })

// "Save as macro" from the chat hands off a draft via macroPrefill → open the
// editor pre-filled (read-and-cleared so a later plain /macros visit is normal).
function _consumeMacroPrefill() {
	const pre = takeMacroPrefill()
	if (!pre) return
	macroError.value = ""
	macroForm.value = _blankMacro()
	if (pre.macro_name) macroForm.value.macro_name = pre.macro_name
	if (pre.description) macroForm.value.description = pre.description
	macroForm.value.steps = (pre.steps && pre.steps.length)
		? pre.steps.map((s) => ({ label: s.label || "", prompt: s.prompt || "", skills: s.skills || [] }))
		: [{ label: "", prompt: "", skills: [] }]
	macroEdTab.value = "steps"
	loadSkillOptions()
	activeTab.value = "macros"
	editorOpen.value = true
}

onMounted(() => {
	socket && socket.on && socket.on("jarvis:event", onEvent)
	if (activeTab.value === "runs") loadMacroRuns(true)
	_consumeMacroPrefill()
})
onBeforeUnmount(() => {
	socket && socket.off && socket.off("jarvis:event", onEvent)
})
</script>

<style scoped>
.mv-name { font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; }
.mv-dash { color: var(--text-3); }
.mv-sub { font-size: 11px; color: var(--text-3); font-weight: 400; }
.mv-runs { padding-top: 2px; }

/* ---- editor: copied verbatim from ChatView's scoped jv-* (component-local via scoping) ---- */
.jv-skill-l { display: block; font-size: 11px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; margin: 0 0 4px; }
.jv-skill-in, .jv-skill-ta { width: 100%; box-sizing: border-box; padding: 8px 10px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; font-family: inherit; font-size: 13px; color: var(--text); outline: none; }
.jv-skill-ta { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; resize: vertical; line-height: 1.5; }
.jv-skill-in:focus, .jv-skill-ta:focus { border-color: var(--blue); }
.jv-skill-err { font-size: 12px; color: var(--red); background: var(--red-bg); border: 1px solid var(--red-bd); border-radius: 7px; padding: 7px 10px; margin-bottom: 10px; }
.jv-set-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--border); font-size: 13px; color: var(--text-2); }
.jv-set-empty { font-size: 12.5px; color: var(--text-3); padding: 14px 0; }
.jv-skill-newrow { display: flex; align-items: center; gap: 8px; width: 100%; justify-content: center; padding: 10px; margin-bottom: 12px; background: var(--blue-bg); border: 1px dashed var(--blue); border-radius: 10px; font-family: inherit; font-size: 13px; font-weight: 600; color: var(--blue); cursor: pointer; }
.jv-skill-newrow:hover { background: var(--blue); color: #fff; }
.jv-skill-newrow:hover svg { stroke: #fff; }
.jv-macro-sched-fields { display: flex; gap: 12px; margin: 8px 0 4px; }
.jv-macro-tabs { display: flex; gap: 4px; margin-top: 16px; border-bottom: 1px solid var(--border); }
.jv-macro-tab { background: none; border: none; border-bottom: 2px solid transparent; color: var(--text-3); font-size: 12.5px; font-weight: 600; padding: 7px 10px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.jv-macro-tab.on { color: var(--text); border-bottom-color: var(--blue); }
.jv-macro-tab-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--green); }
.jv-merge-sub { font-size: 12px; color: var(--text-3); }
.jv-merge-sub b { color: var(--text); }
.jv-merge-text { width: 100%; box-sizing: border-box; background: var(--surface-1); border: 1px solid var(--border-2); border-radius: 9px; color: var(--text); padding: 10px 12px; font-size: 13.5px; line-height: 1.5; resize: vertical; }
.jv-macro-step { border: 1px solid var(--border); border-radius: 11px; padding: 10px; margin-top: 10px; background: var(--surface-1); transition: border-color .12s, box-shadow .12s, opacity .12s, transform .12s; }
.jv-macro-step.dragging { opacity: .45; }
.jv-macro-step.dragover { border-color: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-macro-step-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.jv-macro-grip { flex: none; display: flex; align-items: center; justify-content: center; width: 22px; height: 26px; color: var(--text-3); cursor: grab; border-radius: 6px; transition: background .12s, color .12s; }
.jv-macro-grip:hover { color: var(--text); background: var(--surface-2); }
.jv-macro-grip:active { cursor: grabbing; }
.jv-macro-step-num { flex: none; width: 20px; height: 20px; border-radius: 99px; background: var(--blue-bg); color: var(--blue); font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; }
.jv-macro-step-label { flex: 1; }
.jv-macro-step-skills { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 8px; }
.jv-macro-step-skills-l { display: inline-flex; align-items: center; gap: 4px; font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); margin-right: 2px; }
.jv-macro-skill-opt { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 999px; border: 1px solid var(--border-2); background: var(--surface); color: var(--text-2); font-family: ui-monospace, Menlo, monospace; font-size: 12px; font-weight: 500; cursor: pointer; transition: border-color .12s, background .12s, color .12s, box-shadow .12s; }
.jv-macro-skill-opt--sm { padding: 3px 9px; font-size: 11px; gap: 4px; }
.jv-macro-skill-opt:hover { border-color: var(--blue); color: var(--text); }
.jv-macro-skill-opt.on { background: var(--blue-bg); border-color: var(--blue-bd); color: var(--blue); box-shadow: 0 1px 2px rgba(20, 20, 30, .06); }
.jv-macro-skill-shared { font-family: "Inter", system-ui, sans-serif; font-size: 9.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; padding: 1px 6px; border-radius: 999px; background: var(--amber-bg); color: var(--amber); border: 1px solid var(--amber-bd); }
.jv-ask-tick { color: var(--blue); font-weight: 700; font-size: 11px; }

/* ---- runs dashboard: copied verbatim from ChatView's scoped jv-* ---- */
.jv-statgrid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 11px; }
.jv-stat { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 13px 15px; }
.jv-stat-label { font-size: 10px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; color: var(--text-3); }
.jv-stat-val { font-size: 22px; font-weight: 650; color: var(--text); margin-top: 5px; line-height: 1.05; }
.jv-stat-sub { font-size: 11px; color: var(--text-3); margin-top: 3px; }
.jv-runfilters { display: flex; align-items: center; gap: 10px; margin: 16px 0 6px; flex-wrap: wrap; }
.jv-runchips { display: inline-flex; background: var(--surface-1); border: 1px solid var(--border); border-radius: 9px; padding: 3px; gap: 2px; }
.jv-runchips button { font-family: inherit; font-size: 12px; font-weight: 550; padding: 5px 11px; border-radius: 6px; color: var(--text-3); cursor: pointer; border: none; background: transparent; }
.jv-runchips button.on { background: var(--surface-3); color: var(--text); }
.jv-runmacrosel { margin-left: auto; font-family: inherit; font-size: 12px; color: var(--text-2); background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; cursor: pointer; outline: none; }
.jv-runmacrosel:focus { border-color: var(--blue); }
.jv-run { display: flex; align-items: flex-start; gap: 11px; padding: 12px 2px; border-bottom: 1px solid var(--surface-2); }
.jv-run:last-of-type { border-bottom: none; }
.jv-run-dot { flex: none; width: 9px; height: 9px; border-radius: 50%; margin-top: 5px; }
.jv-run-dot.d-ok { background: var(--green); }
.jv-run-dot.d-err { background: var(--red); }
.jv-run-dot.d-run { background: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-run-dot.d-stop { background: var(--text-3); }
.jv-run-main { flex: 1; min-width: 0; }
.jv-run-top { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
.jv-run-name { font-size: 13.5px; font-weight: 600; color: var(--text); }
.jv-run-badge { font-size: 10.5px; font-weight: 600; padding: 2px 8px; border-radius: 99px; text-transform: capitalize; }
.jv-run-badge.b-ok { background: var(--green-bg); color: var(--green); border: 1px solid var(--green-bd); }
.jv-run-badge.b-err { background: var(--red-bg); color: var(--red); border: 1px solid var(--red-bd); }
.jv-run-badge.b-run { background: var(--blue-bg); color: var(--blue); border: 1px solid var(--blue-bd); }
.jv-run-badge.b-stop { background: var(--surface-2); color: var(--text-3); border: 1px solid var(--border-2); }
.jv-run-trig { display: inline-flex; align-items: center; gap: 4px; font-size: 10.5px; color: var(--text-3); }
.jv-run-meta { display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: var(--text-3); margin-top: 4px; flex-wrap: wrap; }
.jv-run-prog { font-family: ui-monospace, Menlo, monospace; }
.jv-run-sep { opacity: .5; }
.jv-run-err { display: flex; align-items: center; gap: 5px; margin-top: 5px; font-size: 11.5px; color: var(--red); word-break: break-word; }
.jv-run-err svg { flex: none; }
.jv-run-act { display: flex; align-items: center; gap: 6px; flex: none; }
.jv-run-btn { display: inline-flex; align-items: center; gap: 5px; font-family: inherit; font-size: 11.5px; font-weight: 550; padding: 5px 11px; border-radius: 7px; cursor: pointer; background: var(--surface); color: var(--text-2); border: 1px solid var(--border-2); }
.jv-run-btn:hover { color: var(--text); border-color: var(--text-3); }
.jv-run-btn.stop { background: var(--red-bg); color: var(--red); border-color: var(--red-bd); }
.jv-run-btn.stop:hover { background: var(--red); color: #fff; border-color: var(--red); }
.jv-run-loadmore { display: block; margin: 14px auto 2px; font-family: inherit; font-size: 12px; font-weight: 550; color: var(--text-2); background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 8px 18px; cursor: pointer; }
.jv-run-loadmore:disabled { opacity: .6; cursor: default; }

@media (max-width: 640px) {
	.jv-statgrid { grid-template-columns: 1fr 1fr; }
}
</style>
