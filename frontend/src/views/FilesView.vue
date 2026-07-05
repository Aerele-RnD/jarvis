<template>
	<PageShell crumb="File Box" title="File Box"
		subtitle="Drop an inbound document — invoice, receipt, PO — and Jarvis drafts it for you.">
		<!-- ============ DROP ZONE (above the list; exact port of ChatView) ============ -->
		<div class="fv-drop-card">
			<div class="fv-dropzone" :class="{ drag: fileboxDrag }"
				@click="fileboxInput && fileboxInput.click()"
				@dragover.prevent="fileboxDrag = true" @dragleave="fileboxDrag = false"
				@drop.prevent="onFileboxDrop($event)">
				<svg class="fv-drop-ic" width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M17 8l-5-5-5 5" /><path d="M12 3v13" /></svg>
				<div class="fv-drop-main">
					Drop files here, or click to browse<span v-if="fileboxUploading"> — {{ fileboxUploading }} uploading…</span>.
				</div>
				<div class="fv-drop-sub">Keep adding — each file processes in the background and lands in Approvals if it needs you.</div>
				<input ref="fileboxInput" type="file" multiple style="display:none" @change="onFileboxPick($event)" />
			</div>
			<!-- per-file error chips (last 8) -->
			<div v-if="dropErrors.length" class="fv-drop-errs">
				<div v-for="d in dropErrors" :key="d.key" class="fv-drop-err">
					<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16.4v.01" /></svg>
					<span class="fv-drop-err-name">{{ d.name }}</span>: {{ d.error }}
				</div>
			</div>
		</div>

		<!-- ============ LIST ============ -->
		<FeatureListPage ref="flpRef"
			:columns="columns"
			:fetch-fn="fetchFiles"
			:filters-config="filtersConfig"
			:search-config="{ placeholder: 'Search documents', debounceMs: 300 }"
			:sortable-keys="['creation', 'title']"
			:default-sort="{ field: 'creation', dir: 'desc' }"
			:row-actions="rowActions"
			:on-row-click="openChat"
			:selectable="true"
			:bulk-actions="bulkActions"
			:header-actions="headerActions"
			:empty-state="{ title: 'No documents yet.', description: 'Drop a file above and it lands here as it processes.' }"
			@state="onState">
			<template #cell-title="{ row }">
				<svg class="fv-file-ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg>
				<span class="fv-title">{{ strip(row.title) }}</span>
			</template>
			<template #cell-status="{ row }">
				<span class="fp-chip" :class="statusChipClass(row.status)">{{ statusLabel(row) }}</span>
			</template>
		</FeatureListPage>
	</PageShell>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from "vue"
import { useRoute, useRouter } from "vue-router"
import PageShell from "@/components/PageShell.vue"
import FeatureListPage from "@/components/FeatureListPage.vue"
import { useNotify } from "@/composables/useNotify"
import * as api from "@/api"

const route = useRoute()
const router = useRouter()
const { notify, confirmDialog, errMsg } = useNotify()

// ── list config ──────────────────────────────────────────────────────────────
const flpRef = ref(null)
const fetchFiles = (p) => api.fileboxListPage(p)

const columns = [
	{ key: "title", label: "Document", width: 2 },
	{ key: "status", label: "Status", width: 0.9 },
	{ key: "creation", label: "Dropped", width: 0.9, format: (v) => fmtWhen(v) },
]

// status deep-link: seed the filter default from ?status= (validated).
const STATUSES = ["done", "processing", "needs_approval", "error"]
const initialStatus = STATUSES.includes(route.query.status) ? route.query.status : ""
const filtersConfig = [
	{ key: "status", label: "Status", type: "select", default: initialStatus, options: [
		{ label: "All", value: "" },
		{ label: "Done", value: "done" },
		{ label: "Processing", value: "processing" },
		{ label: "Needs approval", value: "needs_approval" },
		{ label: "Error", value: "error" },
	] },
	{ key: "daterange", label: "Dropped", type: "daterange" },
]

const ICON_CHAT = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'
const ICON_TRASH = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>'

function rowActions(row) {
	const processing = row.status === "processing"
	return [
		{ id: "open", label: "Open chat", icon: ICON_CHAT, title: "Open chat", onClick: openChat },
		{ id: "delete", label: "Delete", icon: ICON_TRASH, danger: true, disabled: processing,
			title: processing ? "Still processing — stop or wait first" : "Delete", onClick: deleteRow },
	]
}

const headerActions = [
	{ id: "clear", label: "Clear processed", danger: true, onClick: clearProcessed },
]
const bulkActions = [
	{ label: "Delete selected", danger: true, onClick: bulkDelete },
]

// ── status chip rendering (parity with ChatView.vue:703-709) ─────────────────
function statusChipClass(s) {
	if (s === "needs_approval" || s === "error") return "fp-chip--red"
	if (s === "done") return "fp-chip--green"
	return "fp-chip--muted" // processing
}
function statusLabel(row) {
	if (row.status === "needs_approval") {
		const n = row.pending_approvals || 0
		return `${n} approval${n === 1 ? "" : "s"}`
	}
	return row.status
}

// ── navigation / row actions ─────────────────────────────────────────────────
function openChat(row) {
	router.push("/c/" + row.name)
}
async function deleteRow(row) {
	if (row.status === "processing") return
	if (!(await confirmDialog({
		title: "Delete document?",
		message: "Deletes the conversation, its messages, the uploaded file, and its approval requests.",
		confirmLabel: "Delete",
	}))) return
	try {
		await api.fileboxDelete(row.name)
		flpRef.value && flpRef.value.refresh({ keepPage: true })
		notify("Document deleted", { type: "success" })
	} catch (e) { notify(errMsg(e), { type: "error" }) }
}
async function clearProcessed() {
	if (!(await confirmDialog({
		title: "Clear processed documents?",
		message: "Deletes every done or errored document (with its file, messages, and approvals). Processing and needs-approval documents are kept.",
		confirmLabel: "Clear processed",
	}))) return
	try {
		const res = (await api.fileboxClearProcessed()) || {}
		notify(`${res.deleted || 0} document${(res.deleted || 0) === 1 ? "" : "s"} cleared`, { type: "success" })
		flpRef.value && flpRef.value.refresh()
	} catch (e) { notify(errMsg(e), { type: "error" }) }
}
async function bulkDelete(keys) {
	if (!keys || !keys.length) return
	if (!(await confirmDialog({
		title: `Delete ${keys.length} document${keys.length === 1 ? "" : "s"}?`,
		message: "Deletes the conversations, their messages, the uploaded files, and their approval requests.",
		confirmLabel: "Delete",
	}))) return
	try {
		const res = (await api.fileboxDeleteBulk(keys)) || {}
		const skipped = res.skipped || []
		const deleted = res.deleted != null ? res.deleted : keys.length - skipped.length
		if (skipped.length) {
			notify(`${deleted} deleted · ${skipped.length} skipped (still processing).`, { type: "info", duration: 5000 })
		} else {
			notify(`${deleted} document${deleted === 1 ? "" : "s"} deleted`, { type: "success" })
		}
		flpRef.value && flpRef.value.refresh()
	} catch (e) { notify(errMsg(e), { type: "error" }) }
}

// ── query sync (status only, design §1.1 / §4.3) ─────────────────────────────
function onState(st) {
	const status = (st.filters && st.filters.status) || ""
	const q = { ...route.query }
	if (status) q.status = status
	else delete q.status
	router.replace({ query: q })
}

// ── drop-zone pipeline (EXACT port of ChatView.vue:1656-1749) ────────────────
const fileboxInput = ref(null)
const fileboxDrag = ref(false)
const fileboxUploading = ref(0) // in-flight drops; the box stays open and accepts more
const fileboxDropStatus = ref([]) // per-file: {key, name, state: uploading|ok|error, error}
const dropErrors = ref([]) // last-8 errored files (derived, kept as its own list)

async function _fileboxProcess(file) {
	// Background-first: each file is its own async pipeline. Keep dropping —
	// nothing blocks, nothing navigates; the row appears as "processing" and
	// lands in Approvals if it needs you.
	if (!file) return
	fileboxUploading.value++
	const entry = { key: `${file.name}-${Date.now()}-${Math.random()}`, name: file.name, state: "uploading", error: "" }
	fileboxDropStatus.value = [entry, ...fileboxDropStatus.value].slice(0, 8)
	try {
		const up = await api.uploadFile(file)
		const res = await api.fileboxDrop(up.file_url, up.file_name)
		if (!res || !res.ok) throw new Error((res && res.reason) || "drop failed")
		entry.state = "ok"
		// Optimistic processing row at the top (parity with ChatView; reconciled
		// by the 15s processing-poll below). NO navigation on drop.
		prependOptimistic(res.conversation_id, up.file_name)
	} catch (e) {
		entry.state = "error"
		entry.error = e.message || String(e)
		fileboxDropStatus.value = [...fileboxDropStatus.value]
	} finally {
		fileboxUploading.value--
		syncDropErrors()
	}
}
function syncDropErrors() {
	dropErrors.value = fileboxDropStatus.value.filter((x) => x.state === "error")
}
function prependOptimistic(convId, fileName) {
	const flp = flpRef.value
	if (!flp || !convId) return
	const arr = flp.rows
	if (!arr) return
	const dupe = arr.findIndex((r) => r.name === convId)
	if (dupe >= 0) arr.splice(dupe, 1)
	arr.unshift({
		name: convId,
		title: `File: ${fileName}`,
		creation: new Date().toISOString(),
		status: "processing",
		pending_approvals: 0,
	})
	if (dupe < 0) flp.total = (flp.total || 0) + 1
	ensurePoll()
}
function onFileboxDrop(ev) {
	fileboxDrag.value = false
	const files = (ev.dataTransfer && ev.dataTransfer.files) || []
	for (const f of files) _fileboxProcess(f)
}
function onFileboxPick(ev) {
	const files = ev.target.files || []
	for (const f of files) _fileboxProcess(f)
	ev.target.value = ""
}

// ── freshness: poll while any visible row is processing + refetch on visible ──
let pollTimer = null
function ensurePoll() {
	if (pollTimer) return
	pollTimer = setInterval(() => {
		const flp = flpRef.value
		const arr = (flp && flp.rows) || []
		if (arr.some((r) => r.status === "processing")) {
			flp.refresh({ keepPage: true })
		}
	}, 15000)
}
function onVisibility() {
	if (document.visibilityState === "visible" && flpRef.value) {
		flpRef.value.refresh({ keepPage: true })
	}
}

// ── helpers ──────────────────────────────────────────────────────────────────
function strip(title) {
	return (title || "").replace(/^File: /, "")
}
function fmtWhen(dt) {
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

onMounted(() => {
	ensurePoll() // stays cheap: only refreshes on ticks where a row is processing
	document.addEventListener("visibilitychange", onVisibility)
})
onBeforeUnmount(() => {
	if (pollTimer) clearInterval(pollTimer)
	document.removeEventListener("visibilitychange", onVisibility)
})
</script>

<style scoped>
/* ── drop-zone card (values themed from ChatView's inline filebox styles) ──── */
.fv-drop-card { margin-bottom: 18px; }
.fv-dropzone {
	display: flex; flex-direction: column; align-items: center; gap: 5px;
	border: 2px dashed var(--border); border-radius: 12px; padding: 26px 20px;
	text-align: center; cursor: pointer; color: var(--text-3);
	background: var(--surface); transition: border-color .15s, background .15s;
}
.fv-dropzone:hover { border-color: var(--border-2); }
.fv-dropzone.drag { border-color: var(--blue); background: var(--surface-2); }
.fv-drop-ic { color: var(--text-3); margin-bottom: 2px; }
.fv-dropzone.drag .fv-drop-ic { color: var(--blue); }
.fv-drop-main { font-size: 13px; color: var(--text-2); font-weight: 500; }
.fv-drop-sub { font-size: 11.5px; color: var(--text-3); max-width: 460px; }
.fv-drop-errs { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
.fv-drop-err { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--red); background: var(--red-bg); border: 1px solid var(--red-bd); border-radius: 8px; padding: 6px 10px; }
.fv-drop-err svg { flex: none; }
.fv-drop-err-name { font-weight: 600; }

/* ── list cells ────────────────────────────────────────────────────────────── */
.fv-file-ic { flex: none; color: var(--text-3); }
.fv-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
</style>
