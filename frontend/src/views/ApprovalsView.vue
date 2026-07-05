<template>
	<PageShell crumb="Approvals" title="Approvals"
		subtitle="Decisions waiting on you. Deciding resumes the chat that asked.">
		<!-- live pending count (header, refreshed after each decision) -->
		<template #actions>
			<span v-if="pendingCount > 0" class="av-pending" title="Pending decisions">
				<span class="av-pending-dot"></span>{{ pendingCount }} pending
			</span>
		</template>

		<FeatureListPage ref="flpRef"
			:columns="columns"
			:fetch-fn="fetchApprovals"
			:filters-config="filtersConfig"
			:search-config="{ placeholder: 'Search approvals', debounceMs: 300 }"
			:sortable-keys="['creation', 'document_type']"
			:default-sort="{ field: 'creation', dir: 'desc' }"
			:expandable="true"
			:empty-state="{ title: 'Nothing waiting on you. 🎉', description: 'Decisions your assistant needs from you show up here.' }"
			@state="onState">
			<!-- doc-type chip -->
			<template #cell-document_type="{ row }">
				<span class="fp-chip fp-chip--muted">{{ docType(row) }}</span>
			</template>
			<!-- status chip -->
			<template #cell-status="{ row }">
				<span class="fp-chip" :class="statusChipClass(row.status)">{{ row.status }}</span>
			</template>
			<!-- Asked (ago) -->
			<template #cell-creation="{ row }">{{ fmtAgo(row.creation) }}</template>

			<!-- ============ DECIDE PANEL (exact port of ChatView.vue:742-771) ======= -->
			<template #row-expand="{ row }">
				<div class="av-panel">
					<div class="av-question">{{ row.question }}</div>

					<details v-if="row.context_md" class="av-context">
						<summary>context</summary>
						<pre>{{ row.context_md }}</pre>
					</details>

					<!-- decided rows: verdict line + Chat -->
					<template v-if="row.status !== 'Pending'">
						<div class="av-verdict">
							<b :class="row.status === 'Approved' ? 'ok' : 'no'">{{ row.status }}</b>
							<span v-if="row.decision"> — {{ row.decision }}</span>
							<span class="av-verdict-meta"> · {{ row.decided_by }}<span v-if="row.decided_at"> · {{ fmtWhen(row.decided_at) }}</span></span>
						</div>
						<div v-if="row.conversation" class="av-actions">
							<button class="fp-btn fp-btn--sm fp-btn--ghost" @click="openChat(row)">Chat</button>
						</div>
					</template>

					<!-- pending rows: options + free-text draft + Approve/Reject/Chat -->
					<template v-else>
						<div v-if="row.options && row.options.length" class="av-options">
							<button v-for="opt in row.options" :key="opt" class="fp-btn fp-btn--sm"
								:class="{ 'fp-btn--primary': approvalDrafts[row.name] === opt }"
								@click="approvalDrafts[row.name] = opt">{{ opt }}</button>
						</div>
						<div class="av-decide">
							<input class="fp-in av-draft" v-model="approvalDrafts[row.name]"
								placeholder="Decision (pick an option or type)"
								@keyup.enter="canDecide(row) && decide(row, 1)" />
							<button class="fp-btn fp-btn--primary fp-btn--sm"
								:disabled="!canDecide(row) || busyName === row.name" @click="decide(row, 1)">
								{{ busyName === row.name ? "…" : "Approve" }}
							</button>
							<button class="fp-btn fp-btn--sm fp-btn--danger"
								:disabled="!canDecide(row) || busyName === row.name" @click="decide(row, 0)">Reject</button>
							<button v-if="row.conversation" class="fp-btn fp-btn--sm fp-btn--ghost" title="Open the chat" @click="openChat(row)">Chat</button>
						</div>
					</template>
				</div>
			</template>
		</FeatureListPage>
	</PageShell>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from "vue"
import { useRoute, useRouter } from "vue-router"
import PageShell from "@/components/PageShell.vue"
import FeatureListPage from "@/components/FeatureListPage.vue"
import { useNotify } from "@/composables/useNotify"
import * as api from "@/api"

const route = useRoute()
const router = useRouter()
const { notify, errMsg } = useNotify()

const flpRef = ref(null)

// ── deep-link seeds (status + type from the query, design §1.1 / §4.4) ───────
const STATUS_VALUES = ["Pending", "Decided", "All"]
const initialStatus = STATUS_VALUES.includes(route.query.status) ? route.query.status : "Pending"
const initialType = typeof route.query.type === "string" ? route.query.type : ""

// ── columns ──────────────────────────────────────────────────────────────────
const columns = [
	{ key: "title", label: "Title", width: 1.8 },
	{ key: "document_type", label: "Type", width: 0.9 },
	{ key: "status", label: "Status", width: 0.7 },
	{ key: "creation", label: "Asked", width: 0.7 },
]

// ── document_type facet options (refreshed each page-1 response, §4.4) ───────
const docTypeFacets = ref([]) // [{ value, count }]
const filtersConfig = computed(() => {
	const typeOpts = [{ label: "All types", value: "" }]
	if (docTypeFacets.value.length) {
		for (const f of docTypeFacets.value) typeOpts.push({ label: `${f.value} (${f.count})`, value: f.value })
	} else if (initialType) {
		// keep the deep-linked value selectable before facets arrive
		typeOpts.push({ label: initialType, value: initialType })
	}
	return [
		{ key: "status", label: "View", type: "select", default: initialStatus, options: [
			{ label: "Pending", value: "Pending" },
			{ label: "Decided", value: "Decided" },
			{ label: "All", value: "All" },
		] },
		{ key: "document_type", label: "Type", type: "select", default: initialType, options: typeOpts },
	]
})

// fetchFn wrapper: capture the doc-type facets on page-1 loads so the filter
// dropdown reflects the current (status/search) triage counts.
async function fetchApprovals(p) {
	const res = (await api.listApprovalsPage(p)) || {}
	if ((p.start || 0) === 0 && res.facets && Array.isArray(res.facets.document_type)) {
		docTypeFacets.value = res.facets.document_type
	}
	return res
}

// ── decide flow ──────────────────────────────────────────────────────────────
const approvalDrafts = reactive({}) // { [name]: draftText }
const busyName = ref(null) // busy-guard against double-submit
const pendingCount = ref(0)

function canDecide(row) {
	return !!(approvalDrafts[row.name] || "").trim()
}
async function decide(row, approve) {
	const decision = (approvalDrafts[row.name] || "").trim()
	if (!decision || busyName.value) return // required + busy-guard (server enforces too)
	busyName.value = row.name
	try {
		await api.decideApproval(row.name, decision, approve) // unchanged contract
		// Background-first: the decision resumes the chat over there; stay on the
		// board. Remove the row locally, decrement the footer total, refresh the
		// header pending count.
		removeRowLocal(row.name)
		delete approvalDrafts[row.name]
		refreshPending()
		notify(approve ? "Approved" : "Rejected", { type: "success" })
	} catch (e) {
		notify(`Could not record the decision: ${errMsg(e)}`, { type: "error" })
	} finally {
		busyName.value = null
	}
}
function removeRowLocal(name) {
	const flp = flpRef.value
	if (!flp || !flp.rows) return
	const i = flp.rows.findIndex((r) => r.name === name)
	if (i >= 0) {
		flp.rows.splice(i, 1)
		flp.total = Math.max(0, (flp.total || 0) - 1)
	}
}
async function refreshPending() {
	try { pendingCount.value = (await api.approvalsPendingCount()) || 0 } catch (e) { /* best-effort */ }
}

function openChat(row) {
	if (row.conversation) router.push("/c/" + row.conversation)
}

// ── query sync (status + type, design §1.1 / §4.4) ───────────────────────────
function onState(st) {
	const status = (st.filters && st.filters.status) || ""
	const type = (st.filters && st.filters.document_type) || ""
	const q = { ...route.query }
	// "Pending" is the default view — keep the URL clean when it's the default.
	if (status && status !== "Pending") q.status = status
	else delete q.status
	if (type) q.type = type
	else delete q.type
	router.replace({ query: q })
}

// ── freshness: refetch on tab-visible (no realtime approval event today) ─────
function onVisibility() {
	if (document.visibilityState === "visible" && flpRef.value) {
		flpRef.value.refresh({ keepPage: true })
		refreshPending()
	}
}

// ── cell helpers ─────────────────────────────────────────────────────────────
function docType(row) {
	return (row.document_type || "").trim() || "Unclassified"
}
function statusChipClass(s) {
	if (s === "Approved") return "fp-chip--green"
	if (s === "Rejected") return "fp-chip--red"
	return "fp-chip--amber" // Pending
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
	if (!dt) return ""
	const t = new Date(String(dt).replace(" ", "T")).getTime()
	if (isNaN(t)) return ""
	return new Date(t).toLocaleString()
}

onMounted(() => {
	refreshPending()
	document.addEventListener("visibilitychange", onVisibility)
})
onBeforeUnmount(() => {
	document.removeEventListener("visibilitychange", onVisibility)
})
</script>

<style scoped>
/* header pending pill */
.av-pending { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--amber); background: rgba(245, 158, 11, .14); border-radius: 999px; padding: 5px 11px; }
.av-pending-dot { width: 7px; height: 7px; border-radius: 999px; background: var(--amber); flex: none; }

/* ── decide panel (#row-expand) — themed port of ChatView.vue:742-771 ──────── */
.av-panel { display: flex; flex-direction: column; gap: 10px; padding-top: 8px; }
.av-question { font-size: 13px; color: var(--text); line-height: 1.5; }
.av-context { font-size: 11.5px; }
.av-context summary { color: var(--text-3); cursor: pointer; user-select: none; }
.av-context pre { margin: 6px 0 0; font-size: 11px; white-space: pre-wrap; max-height: 180px; overflow: auto; background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 9px 11px; color: var(--text-2); }

.av-verdict { font-size: 12.5px; color: var(--text-2); }
.av-verdict b { font-weight: 650; }
.av-verdict b.ok { color: var(--green); }
.av-verdict b.no { color: var(--red); }
.av-verdict-meta { color: var(--text-3); }

.av-options { display: flex; gap: 6px; flex-wrap: wrap; }
.av-decide { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.av-draft { flex: 1 1 240px; min-width: 180px; height: 32px; }
.av-actions { display: flex; gap: 6px; }
</style>
