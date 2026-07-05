<template>
	<PageShell crumb="Skills" title="Skills"
		subtitle="Abilities your assistant can use — type / in chat to trigger one."
		@esc="onEsc">
		<!-- sync pill: EXACTLY like ChatView (visible only while pending or failed) -->
		<template #banner>
			<div v-if="skillsSync.pending || skillsSync.last_sync_status.startsWith('failed')"
				class="sv-sync" :class="{ err: skillsSync.last_sync_status.startsWith('failed') }">
				<template v-if="skillsSync.pending"><span class="sv-dot spin"></span> Updating your assistant… (restarts briefly, ~30s)</template>
				<template v-else><span class="sv-dot err"></span> Couldn't update your assistant. {{ skillsSync.last_sync_status.replace("failed:", "").trim() }}</template>
			</div>
		</template>

		<!-- New (primary) -->
		<template #actions>
			<button class="fp-btn fp-btn--primary fp-btn--sm" @click="newSkill">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg> New
			</button>
		</template>

		<FeatureListPage ref="flpRef"
			:columns="columns"
			:fetch-fn="fetchSkills"
			:filters-config="filtersConfig"
			:search-config="{ placeholder: 'Search skills', debounceMs: 300 }"
			:sortable-keys="['skill_name', 'modified']"
			:default-sort="{ field: 'skill_name', dir: 'asc' }"
			:row-actions="rowActions"
			:on-row-click="editSkill"
			:empty-state="{ title: 'No skills yet.', description: 'Create one to give your assistant a new ability.' }">
			<template #cell-skill_name="{ row }">
				<span class="sv-name">/{{ row.skill_name }}</span>
				<span v-if="!row.enabled" class="sv-off">draft</span>
			</template>
			<template #cell-owner_display="{ row }">
				<span v-if="row.mine" class="sv-owner">You</span>
				<span v-else class="sv-owner sv-owner--shared" :title="'Shared by ' + (row.shared_by || 'another user') + ' · read-only'">
					<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
					{{ row.shared_by || "another user" }}
				</span>
			</template>
			<template #cell-shared_count="{ row }">
				<span v-if="row.mine && row.shared_count > 0" class="sv-shared" title="Shared with people">
					<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3" /><circle cx="6" cy="12" r="3" /><circle cx="18" cy="19" r="3" /><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" /></svg>{{ row.shared_count }}
				</span>
				<span v-else class="sv-dash">—</span>
			</template>
		</FeatureListPage>

		<!-- ============ EDIT / VIEW DRAWER (560px) ============ -->
		<JvDrawer v-model="drawerOpen" :width="560"
			:title="skillReadonly ? 'Skill' : (skillForm.name ? 'Edit skill' : 'New skill')"
			:subtitle="skillReadonly ? '' : 'Type /' + (skillForm.skill_name || 'name') + ' in chat to trigger it.'">
			<div v-if="skillError" class="fp-err">{{ skillError }}</div>
			<div v-if="skillReadonly" class="sv-ro">
				<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
				<span>Shared by <b>{{ skillSharedBy || "another user" }}</b> · read-only</span>
			</div>
			<label class="fp-l">Name</label>
			<input class="fp-in" v-model="skillForm.skill_name" :disabled="skillReadonly || !!skillForm.name" placeholder="e.g. monthly-close" maxlength="40" />
			<div v-if="!skillReadonly" class="sv-hint">Lowercase letters, digits and hyphens. Trigger it in chat with /{{ skillForm.skill_name || 'name' }}.</div>
			<div v-else style="height:10px;"></div>
			<label class="fp-l">Description</label>
			<input class="fp-in" v-model="skillForm.description" :disabled="skillReadonly" placeholder="When should the assistant use this skill?" maxlength="500" />
			<div v-if="!skillReadonly" class="sv-hint">A short hint so the assistant knows when this skill applies.</div>
			<div v-else style="height:10px;"></div>
			<label class="fp-l">Instructions</label>
			<textarea class="fp-in sv-ta" v-model="skillForm.instructions" :disabled="skillReadonly" rows="12" placeholder="Markdown instructions the assistant follows when this skill runs…"></textarea>
			<div v-if="!skillReadonly" class="sv-row" style="margin-top:12px;">
				<span>Let users trigger it with /<br /><span class="sv-row-sub">Appears in the chat “/” menu</span></span>
				<button class="fp-switch" :class="{ on: skillForm.user_invocable }" @click="skillForm.user_invocable = !skillForm.user_invocable" role="switch" :aria-checked="String(!!skillForm.user_invocable)"><span class="fp-switch-knob"></span></button>
			</div>
			<div v-if="!skillReadonly" class="sv-row">
				<span>Enabled<br /><span class="sv-row-sub">Off = saved as a draft, not used by the assistant</span></span>
				<button class="fp-switch" :class="{ on: skillForm.enabled }" @click="skillForm.enabled = !skillForm.enabled" role="switch" :aria-checked="String(!!skillForm.enabled)"><span class="fp-switch-knob"></span></button>
			</div>

			<template #footer>
				<button v-if="!skillReadonly" class="fp-btn fp-btn--primary" :disabled="skillSaving || skillsSync.pending" @click="saveSkill">{{ skillSaving ? "Saving…" : "Save skill" }}</button>
				<button v-if="skillReadonly" class="fp-btn fp-btn--ghost" @click="drawerOpen = false">Back</button>
				<button v-else class="fp-btn fp-btn--ghost" :disabled="skillSaving" @click="drawerOpen = false">Cancel</button>
				<span v-if="!skillReadonly" class="sv-foothint">Saving updates your assistant automatically.</span>
			</template>
		</JvDrawer>

		<!-- ============ SHARE DIALOG (centered) ============ -->
		<transition name="fp-fade">
			<div v-if="shareOpen" class="fp-overlay" @click.self="closeShare">
				<div class="sv-sharedlg" role="dialog" aria-modal="true">
					<div class="sv-sharedlg-head">
						<div style="min-width:0;">
							<div class="sv-sharedlg-title">Share “{{ shareSkill.skill_name }}”</div>
							<div class="sv-sharedlg-sub">They can use this skill in chat, but can’t edit or re-share it.</div>
						</div>
						<button class="fp-btn fp-btn--icon" title="Close (Esc)" @click="closeShare">
							<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
						</button>
					</div>
					<div class="sv-sharedlg-body">
						<div v-if="shareLoading" class="sv-empty">Loading people…</div>
						<template v-else>
							<div v-if="shareSelected.length" class="sv-chips">
								<span v-for="id in shareSelected" :key="id" class="sv-chip">
									<span class="sv-avatar">{{ _shareInitials(_shareUser(id)) }}</span>
									<span class="sv-chip-name">{{ _shareUser(id).full_name }}</span>
									<button class="sv-chip-x" title="Remove" @click="toggleShareUser(id)"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg></button>
								</span>
							</div>
							<div class="sv-searchwrap">
								<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
								<input v-model="shareSearch" class="sv-search" placeholder="Search people…" />
							</div>
							<div v-if="!shareCandidates.length" class="sv-empty">No other users to share with yet.</div>
							<div v-else-if="!shareMatches.length" class="sv-empty">No people match “{{ shareSearch }}”.</div>
							<div v-else class="sv-people">
								<button v-for="u in shareMatches" :key="u.name" class="sv-person" :class="{ on: isShareSelected(u.name) }" @click="toggleShareUser(u.name)">
									<span class="sv-avatar">{{ _shareInitials(u) }}</span>
									<span class="sv-person-info">
										<span class="sv-person-name">{{ u.full_name }}</span>
										<span class="sv-person-id">{{ u.name }}</span>
									</span>
									<svg v-if="isShareSelected(u.name)" class="sv-check" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
								</button>
							</div>
							<div class="sv-helper">
								<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 0 1 8 0v4" /></svg>
								They can use this skill in chat, but can’t edit or re-share it.
							</div>
						</template>
					</div>
					<div v-if="!shareLoading" class="sv-sharedlg-foot">
						<button class="fp-btn fp-btn--primary" :disabled="shareSaving" @click="saveShares">{{ shareSaving ? "Saving…" : "Save" }}</button>
						<button class="fp-btn fp-btn--ghost" :disabled="shareSaving" @click="closeShare">Cancel</button>
						<span class="sv-foothint">{{ shareSelected.length }} {{ shareSelected.length === 1 ? "person" : "people" }} selected</span>
					</div>
				</div>
			</div>
		</transition>
	</PageShell>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from "vue"
import PageShell from "@/components/PageShell.vue"
import FeatureListPage from "@/components/FeatureListPage.vue"
import JvDrawer from "@/components/JvDrawer.vue"
import { useNotify } from "@/composables/useNotify"
import * as api from "@/api"

const { notify, confirmDialog, errMsg } = useNotify()

// ── list config ──────────────────────────────────────────────────────────────
const flpRef = ref(null)
const fetchSkills = (p) => api.listCustomSkillsPage(p)
const columns = [
	{ key: "skill_name", label: "Skill", width: 1.3 },
	{ key: "description", label: "Description", width: 2 },
	{ key: "owner_display", label: "Owner", width: 0.9 },
	{ key: "shared_count", label: "Shared", width: 0.5, align: "center" },
	{ key: "modified", label: "Updated", width: 0.7, format: (v) => fmtAgo(v) },
]
const filtersConfig = [
	{ key: "scope", label: "Scope", type: "select", default: "", options: [
		{ label: "All scopes", value: "" }, { label: "Mine", value: "mine" }, { label: "Shared with me", value: "shared" } ] },
	{ key: "enabled", label: "Status", type: "select", default: "", options: [
		{ label: "All", value: "" }, { label: "Enabled", value: 1 }, { label: "Draft", value: 0 } ] },
]

const ICON_SHARE = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"/></svg>'
const ICON_EDIT = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>'
const ICON_VIEW = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>'
const ICON_TRASH = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>'

function rowActions(row) {
	const acts = []
	if (row.mine) acts.push({ id: "share", label: "Share", icon: ICON_SHARE, title: "Share", onClick: openShare })
	acts.push({ id: "edit", label: row.mine ? "Edit" : "View", icon: row.mine ? ICON_EDIT : ICON_VIEW, title: row.mine ? "Edit" : "View", onClick: editSkill })
	if (row.mine) acts.push({ id: "delete", label: "Delete", icon: ICON_TRASH, danger: true, title: "Delete", onClick: removeSkill })
	return acts
}

// ── sync pill + auto-apply ───────────────────────────────────────────────────
const skillsSync = reactive({ last_sync_status: "", pending: false })
let _skillsPoll = null
async function loadSkillsSync() {
	try {
		const s = (await api.getCustomSkillsSyncStatus()) || {}
		skillsSync.last_sync_status = s.last_sync_status || ""
		skillsSync.pending = !!s.pending
	} catch (e) { /* ignore */ }
}
// Saving/deleting pushes the current skill set to the assistant (the old
// "Apply", now automatic). No confirm: an empty set legitimately clears them.
async function syncSkills() {
	try {
		await api.applyCustomSkills()
		skillsSync.last_sync_status = "pending: applying skills"
		skillsSync.pending = true
		if (_skillsPoll) clearInterval(_skillsPoll)
		_skillsPoll = setInterval(async () => {
			await loadSkillsSync()
			if (!skillsSync.pending) { clearInterval(_skillsPoll); _skillsPoll = null }
		}, 3000)
	} catch (e) { notify(errMsg(e), { type: "error" }) }
}

// ── edit / view drawer ───────────────────────────────────────────────────────
const drawerOpen = ref(false)
const skillForm = ref({ name: "", skill_name: "", description: "", instructions: "", user_invocable: true, enabled: true })
const skillReadonly = ref(false)
const skillSharedBy = ref("")
const skillError = ref("")
const skillSaving = ref(false)

function newSkill() {
	skillError.value = ""
	skillReadonly.value = false
	skillSharedBy.value = ""
	skillForm.value = { name: "", skill_name: "", description: "", instructions: "", user_invocable: true, enabled: true }
	drawerOpen.value = true
}
async function editSkill(s) {
	skillError.value = ""
	// Shared-with-me skills open read-only: no editing, saving or toggles.
	skillReadonly.value = !s.mine
	skillSharedBy.value = ""
	try {
		const full = await api.getCustomSkill(s.name)
		skillForm.value = {
			name: full.name, skill_name: full.skill_name, description: full.description || "",
			instructions: full.instructions || "", user_invocable: !!full.user_invocable, enabled: !!full.enabled,
		}
		if (full.can_edit === 0 || !s.mine) skillReadonly.value = true
		skillSharedBy.value = full.shared_by || s.shared_by || ""
		drawerOpen.value = true
	} catch (e) { skillError.value = errMsg(e); drawerOpen.value = true }
}
async function saveSkill() {
	skillError.value = ""
	skillSaving.value = true
	try {
		const f = skillForm.value
		const payload = {
			skill_name: (f.skill_name || "").trim().toLowerCase(),
			description: f.description, instructions: f.instructions,
			user_invocable: f.user_invocable ? 1 : 0, enabled: f.enabled ? 1 : 0,
		}
		if (f.name) await api.updateCustomSkill({ name: f.name, ...payload })
		else await api.createCustomSkill(payload)
		drawerOpen.value = false
		flpRef.value && flpRef.value.refresh()
		syncSkills() // saving pushes to the assistant automatically
	} catch (e) { skillError.value = errMsg(e) } finally { skillSaving.value = false }
}
async function removeSkill(s) {
	if (!(await confirmDialog({ title: "Delete skill?", message: `Delete “${s.skill_name}”? It will be removed from your assistant.`, confirmLabel: "Delete" }))) return
	try {
		await api.deleteCustomSkill(s.name)
		flpRef.value && flpRef.value.refresh()
		syncSkills() // deleting updates the assistant automatically
		notify("Skill deleted", { type: "success" })
	} catch (e) { notify(errMsg(e), { type: "error" }) }
}

// ── share dialog ─────────────────────────────────────────────────────────────
const shareOpen = ref(false)
const shareSkill = ref({ name: "", skill_name: "" })
const shareSearch = ref("")
const shareCandidates = ref([]) // [{name, full_name}]
const shareSelected = ref([]) // user ids
const shareLoading = ref(false)
const shareSaving = ref(false)

const shareMatches = computed(() => {
	const q = (shareSearch.value || "").trim().toLowerCase()
	if (!q) return shareCandidates.value
	return shareCandidates.value.filter((u) =>
		(u.full_name || "").toLowerCase().includes(q) || (u.name || "").toLowerCase().includes(q))
})
function _shareInitials(u) {
	const s = ((u && (u.full_name || u.name)) || "").trim()
	if (!s) return "?"
	const parts = s.split(/\s+/).filter(Boolean)
	if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
	return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}
function _shareUser(id) {
	return shareCandidates.value.find((u) => u.name === id) || { name: id, full_name: id }
}
function isShareSelected(id) { return shareSelected.value.includes(id) }
function toggleShareUser(id) {
	if (shareSelected.value.includes(id)) shareSelected.value = shareSelected.value.filter((x) => x !== id)
	else shareSelected.value = [...shareSelected.value, id]
}
async function openShare(s) {
	shareSkill.value = { name: s.name, skill_name: s.skill_name }
	shareSearch.value = ""
	shareSelected.value = []
	shareCandidates.value = []
	shareOpen.value = true
	shareLoading.value = true
	try {
		const [cand, shares] = await Promise.all([api.listShareableUsers(), api.getSkillShares(s.name)])
		shareCandidates.value = cand || []
		shareSelected.value = ((shares && shares.users) || []).map((u) => u.name)
		const known = new Set(shareCandidates.value.map((u) => u.name))
		for (const u of ((shares && shares.users) || [])) {
			if (!known.has(u.name)) { shareCandidates.value.push({ name: u.name, full_name: u.full_name || u.name }); known.add(u.name) }
		}
	} catch (e) { notify(errMsg(e), { type: "error" }) } finally { shareLoading.value = false }
}
function closeShare() { shareOpen.value = false; shareSaving.value = false }
async function saveShares() {
	shareSaving.value = true
	try {
		await api.shareCustomSkill(shareSkill.value.name, [...shareSelected.value])
		flpRef.value && flpRef.value.refresh()
		notify("Sharing updated", { type: "success" })
		closeShare()
	} catch (e) { notify(errMsg(e), { type: "error" }); shareSaving.value = false }
}

function onEsc() {
	if (shareOpen.value) closeShare()
}

// ── helper ───────────────────────────────────────────────────────────────────
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

onMounted(() => { loadSkillsSync() })
onBeforeUnmount(() => { if (_skillsPoll) clearInterval(_skillsPoll) })
</script>

<style scoped>
/* sync pill (copied from ChatView .jv-skills-status / .jv-skill-dot) */
.sv-sync { display: flex; align-items: center; gap: 7px; font-size: 11.5px; color: var(--text-3); padding: 9px 13px; background: var(--surface-1); border: 1px solid var(--border); border-radius: 9px; }
.sv-sync.err { color: var(--red); }
.sv-dot { width: 7px; height: 7px; border-radius: 99px; background: var(--text-3); flex: none; }
.sv-dot.err { background: var(--red); }
.sv-dot.spin { border: 2px solid var(--border-2); border-top-color: var(--blue); background: transparent; width: 11px; height: 11px; animation: sv-spin .7s linear infinite; }
@keyframes sv-spin { to { transform: rotate(360deg); } }

/* list cells */
.sv-name { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; }
.sv-off { flex: none; font-size: 9.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; }
.sv-owner { display: inline-flex; align-items: center; gap: 4px; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; }
.sv-owner--shared { color: var(--text-3); }
.sv-owner--shared svg { flex: none; stroke: var(--text-3); }
.sv-shared { display: inline-flex; align-items: center; gap: 4px; padding: 1px 7px 1px 6px; background: var(--blue-bg); color: var(--blue); border-radius: 999px; font-size: 10.5px; font-weight: 600; }
.sv-shared svg { stroke: var(--blue); }
.sv-dash { color: var(--text-3); }

/* drawer form */
.sv-ta { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; line-height: 1.5; min-height: 200px; resize: vertical; }
.sv-hint { font-size: 11.5px; color: var(--text-3); margin: 3px 0 10px; }
.sv-ro { display: flex; align-items: center; gap: 8px; padding: 9px 11px; margin-bottom: 13px; background: var(--blue-bg); border: 1px solid var(--blue-bd); border-radius: 9px; font-size: 12.5px; color: var(--text-2); }
.sv-ro svg { stroke: var(--blue); flex: none; }
.sv-ro b { color: var(--text); font-weight: 600; }
.sv-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 9px 0; border-bottom: 1px solid var(--border); font-size: 13px; color: var(--text-2); }
.sv-row:last-of-type { border-bottom: 0; }
.sv-row-sub { font-size: 11px; color: var(--text-3); font-weight: 400; }
.sv-foothint { font-size: 11px; color: var(--text-3); }

/* share dialog */
.sv-sharedlg { width: 480px; max-width: 100%; max-height: 82vh; display: flex; flex-direction: column; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; overflow: hidden; box-shadow: 0 24px 70px rgba(20, 20, 30, .28); animation: sv-popin .16s ease; }
@keyframes sv-popin { from { transform: scale(.97); opacity: 0; } to { transform: scale(1); opacity: 1; } }
.sv-sharedlg-head { display: flex; align-items: flex-start; gap: 12px; padding: 16px 18px; border-bottom: 1px solid var(--border); }
.sv-sharedlg-title { font-size: 15px; font-weight: 650; color: var(--text); }
.sv-sharedlg-sub { margin-top: 3px; font-size: 12px; color: var(--text-3); }
.sv-sharedlg-body { flex: 1; min-height: 0; overflow-y: auto; padding: 16px 18px; }
.sv-sharedlg-foot { flex: none; display: flex; align-items: center; gap: 10px; padding: 14px 18px; border-top: 1px solid var(--border); background: var(--surface-1); }
.sv-empty { font-size: 12.5px; color: var(--text-3); text-align: center; padding: 22px 0; }
.sv-chips { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 12px; }
.sv-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 6px 3px 3px; background: var(--surface-1); border: 1px solid var(--border-2); border-radius: 999px; font-size: 12px; color: var(--text); }
.sv-chip-name { font-weight: 500; max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sv-chip-x { flex: none; width: 18px; height: 18px; display: flex; align-items: center; justify-content: center; border: none; background: transparent; border-radius: 50%; color: var(--text-3); cursor: pointer; padding: 0; }
.sv-chip-x:hover { background: var(--red-bg); color: var(--red); }
.sv-avatar { flex: none; width: 26px; height: 26px; border-radius: 50%; display: flex; align-items: center; justify-content: center; background: var(--blue); color: #fff; font-size: 10.5px; font-weight: 600; }
.sv-searchwrap { display: flex; align-items: center; gap: 8px; padding: 8px 11px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 9px; margin-bottom: 10px; color: var(--text-3); }
.sv-searchwrap:focus-within { border-color: var(--blue); }
.sv-search { flex: 1; border: none; outline: none; background: transparent; font-family: inherit; font-size: 13px; color: var(--text); }
.sv-people { display: flex; flex-direction: column; gap: 2px; max-height: 280px; overflow-y: auto; margin: 0 -6px; }
.sv-person { display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 10px; background: transparent; border: none; border-radius: 9px; cursor: pointer; text-align: left; }
.sv-person:hover { background: var(--surface-1); }
.sv-person.on { background: var(--blue-bg); }
.sv-person-info { display: flex; flex-direction: column; min-width: 0; flex: 1; line-height: 1.25; }
.sv-person-name { font-size: 13px; font-weight: 550; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sv-person-id { font-size: 11px; color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sv-check { flex: none; stroke: var(--blue); }
.sv-helper { display: flex; align-items: center; gap: 7px; margin-top: 13px; padding: 9px 11px; background: var(--surface-1); border: 1px solid var(--border); border-radius: 9px; font-size: 11.5px; color: var(--text-3); line-height: 1.4; }
.sv-helper svg { stroke: var(--text-3); flex: none; }
</style>
