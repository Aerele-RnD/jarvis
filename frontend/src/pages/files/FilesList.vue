<template>
	<div
		class="relative flex h-full flex-col overflow-hidden"
		@dragenter.prevent="onDragEnter"
		@dragover.prevent
		@dragleave="onDragLeave"
		@drop.prevent="onDrop"
	>
		<ListPage
			:breadcrumbs="[{ label: 'File Box', route: { name: 'FilesList' } }]"
			:columns="columns"
			:rows="rows"
			:loading="loading"
			:total="total"
			:has-more="hasMore"
			:quick-filters="quickFilters"
			:filter-defs="filterDefs"
			:filters="filters"
			:sort-options="sortOptions"
			:sort="sort"
			:page-length="pageLength"
			:default-sort="DEFAULT_SORT"
			:selectable="true"
			:on-row-click="openChat"
			storage-key="files"
			:empty-state="{
				icon: 'inbox',
				title: 'No files yet',
				description: 'Add or drop a document and Jarvis will process it.',
			}"
			@update:filters="onFiltersUpdate"
			@update:sort="(s) => setSort(s.field, s.dir)"
			@update:page-length="(v) => (pageLength = v)"
			@load-more="loadMore"
			@refresh="resetLoad"
		>
			<template #right-header>
				<Button label="Clear Processed" @click="clearProcessed" />
				<Button variant="solid" label="Add Files" iconLeft="upload-cloud" @click="pickFiles" />
			</template>

			<template #cell-title="{ row }">
				<div class="flex items-center gap-2 overflow-hidden">
					<FeatherIcon name="file-text" class="size-4 shrink-0 text-ink-gray-5" />
					<div class="truncate text-base">{{ stripTitle(row.title) }}</div>
				</div>
			</template>

			<template #cell-status="{ row }">
				<Badge
					variant="subtle"
					:theme="(STATUS_BADGE[row.status] || {}).theme || 'gray'"
					:label="(STATUS_BADGE[row.status] || {}).label || row.status"
				/>
			</template>

			<template #cell-creation="{ row }">
				<div class="flex w-full items-center justify-end">
					<Tooltip :text="exactDate(row.creation)">
						<div class="truncate text-base">{{ timeAgo(row.creation) }}</div>
					</Tooltip>
				</div>
			</template>

			<template #select-actions="{ selections, unselectAll }">
				<Dropdown :options="[{ label: 'Delete', onClick: () => bulkDelete(selections, unselectAll) }]">
					<Button icon="more-horizontal" variant="ghost" />
				</Dropdown>
			</template>
		</ListPage>

		<input ref="fileInput" type="file" multiple class="hidden" @change="onPick" />

		<!-- drag-drop overlay -->
		<div
			v-if="dragging"
			class="absolute inset-0 z-10 grid place-items-center rounded-lg border-2 border-dashed border-outline-gray-3 bg-surface-white/90"
		>
			<div class="text-base font-medium text-ink-gray-8">Drop files to add to File Box</div>
		</div>
	</div>
</template>

<script setup>
// File Box list — DESIGN-V3 §5.7 + §15.1: search quick filter (envelope
// `search`), drop overlay + picker upload (toast.promise batch), status quick
// filter with ?status= deep link, date-range filter, processing poll (5s) +
// visibilitychange refresh, bulk delete with skip reasons, Clear Processed.
import { ref, computed, onMounted, onBeforeUnmount } from "vue"
import { useRoute, useRouter } from "vue-router"
import { Button, Badge, FeatherIcon, Tooltip, Dropdown, toast, confirmDialog } from "frappe-ui"
import ListPage from "@/components/list/ListPage.vue"
import { useListPage } from "@/composables/useListPage"
import { useShellStore } from "@/stores/shell"
import { timeAgo, exactDate } from "@/utils/datetime"
import * as api from "@/api"

const route = useRoute()
const router = useRouter()
const store = useShellStore()

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

// ── list config ──────────────────────────────────────────────────────────────
const STATUS_BADGE = {
	done: { label: "Done", theme: "green" },
	processing: { label: "Processing", theme: "blue" },
	needs_approval: { label: "Needs approval", theme: "orange" },
	error: { label: "Error", theme: "red" },
}
const STATUS_OPTIONS = [
	{ label: "All", value: "" },
	{ label: "Processing", value: "processing" },
	{ label: "Needs approval", value: "needs_approval" },
	{ label: "Done", value: "done" },
	{ label: "Error", value: "error" },
]
const STATUSES = ["done", "processing", "needs_approval", "error"]

const columns = [
	{ label: "File", key: "title", width: 3 },
	{ label: "Status", key: "status", width: "9rem" },
	{ label: "Added", key: "creation", width: "8rem", align: "right" },
]
// search rides the quick-filter strip (§15.1): it lives in the filters object
// so the input stays controlled, and fetchFn moves it onto the envelope's
// `search` param (backend matches the title).
const quickFilters = [
	{ key: "search", label: "Search files", type: "text" },
	{ key: "status", label: "Status", type: "select", options: STATUS_OPTIONS },
]
const filterDefs = [
	{ key: "status", label: "Status", type: "select", options: STATUS_OPTIONS },
	{ key: "daterange", label: "Added", type: "daterange" },
]
const sortOptions = [
	{ label: "Added", value: "creation" },
	{ label: "File", value: "title" },
]
const DEFAULT_SORT = { field: "creation", dir: "desc" }

// status deep link: seed the filter from ?status= (validated set, parity)
const initialStatus = STATUSES.includes(route.query.status) ? route.query.status : ""

const {
	rows,
	total,
	hasMore,
	loading,
	filters,
	setFilters,
	sort,
	setSort,
	pageLength,
	resetLoad,
	loadMore,
	refreshKeep,
} = useListPage({
	fetchFn: (p) => {
		// the backend whitelists filter keys and throws on "search" — strip it
		// out of filters and send it as the envelope's search param instead
		const { search: q, ...rest } = p.filters || {}
		return api.fileboxListPage({ ...p, search: q || p.search || "", filters: rest })
	},
	defaultSort: DEFAULT_SORT,
	storageKey: "files",
	initialFilters: initialStatus ? { status: initialStatus } : {},
})

function onFiltersUpdate(next) {
	setFilters(next)
	syncStatusQuery()
}
// keep ?status= in the URL so breadcrumb returns preserve the filter (D32)
function syncStatusQuery() {
	const q = { ...route.query }
	if (filters.status) q.status = filters.status
	else delete q.status
	router.replace({ query: q })
}

function openChat(row) {
	router.push("/c/" + row.name)
}

// ── upload (picker + drag-drop) ──────────────────────────────────────────────
const fileInput = ref(null)
function pickFiles() {
	fileInput.value && fileInput.value.click()
}
function onPick(ev) {
	uploadBatch(ev.target.files)
	ev.target.value = ""
}

async function uploadBatch(fileList) {
	const files = Array.from(fileList || [])
	if (!files.length) return
	const failures = []
	let okCount = 0
	const run = (async () => {
		await Promise.all(
			files.map(async (file) => {
				try {
					const up = await api.uploadFile(file)
					const res = await api.fileboxDrop(up.file_url, up.file_name)
					if (!res || !res.ok) throw new Error((res && res.reason) || "drop failed")
					okCount++
				} catch (e) {
					failures.push({ name: file.name, error: errMsg(e) })
				}
			})
		)
		if (!okCount) throw new Error("upload failed")
		return okCount
	})()
	try {
		await toast.promise(run, {
			loading: `Uploading ${files.length} file${files.length === 1 ? "" : "s"}…`,
			success: (n) => `Added ${n} file${n === 1 ? "" : "s"} to File Box`,
			error: () => "Upload failed",
		})
	} catch (e) {
		// every file failed — the per-file toasts below carry the reasons
	}
	for (const f of failures) toast.error(`${f.name}: ${f.error}`)
	if (okCount) resetLoad()
}

// ── drag-drop overlay ────────────────────────────────────────────────────────
const dragDepth = ref(0)
const dragging = computed(() => dragDepth.value > 0)
function hasFiles(ev) {
	const types = (ev.dataTransfer && ev.dataTransfer.types) || []
	return Array.from(types).includes("Files")
}
function onDragEnter(ev) {
	if (hasFiles(ev)) dragDepth.value++
}
function onDragLeave() {
	dragDepth.value = Math.max(0, dragDepth.value - 1)
}
function onDrop(ev) {
	dragDepth.value = 0
	uploadBatch(ev.dataTransfer && ev.dataTransfer.files)
}

// ── bulk delete + clear processed ────────────────────────────────────────────
function bulkDelete(selections, unselectAll) {
	const names = Array.from(selections || [])
	if (!names.length) return
	confirmDialog({
		title: `Delete ${names.length} document${names.length === 1 ? "" : "s"}?`,
		message:
			"Deletes the conversations, their messages, the uploaded files, and their approval requests.",
		onConfirm: async ({ hideDialog }) => {
			try {
				const res = (await api.fileboxDeleteBulk(names)) || {}
				const skipped = res.skipped || []
				const deleted = res.deleted != null ? res.deleted : names.length - skipped.length
				if (skipped.length) {
					const reasons = [...new Set(skipped.map((s) => s.reason || "skipped"))].join(", ")
					toast.create({
						message: `${deleted} deleted · ${skipped.length} skipped (${reasons})`,
						type: "info",
					})
				} else {
					toast.success(`${deleted} document${deleted === 1 ? "" : "s"} deleted`)
				}
				unselectAll()
				hideDialog()
				resetLoad()
				store.refreshApprovalsCount()
			} catch (e) {
				toast.error(errMsg(e))
			}
		},
	})
}

function clearProcessed() {
	confirmDialog({
		title: "Clear processed documents?",
		message:
			"Deletes every done or errored document (with its file, messages, and approvals). Processing and needs-approval documents are kept.",
		onConfirm: async ({ hideDialog }) => {
			try {
				const res = (await api.fileboxClearProcessed()) || {}
				toast.success(`${res.deleted || 0} document${(res.deleted || 0) === 1 ? "" : "s"} cleared`)
				hideDialog()
				resetLoad()
			} catch (e) {
				toast.error(errMsg(e))
			}
		},
	})
}

// ── freshness: poll while any visible row is processing + refetch on visible ──
let pollTimer = null
function onVisibility() {
	if (document.visibilityState === "visible") refreshKeep()
}
onMounted(() => {
	// cheap tick: only refetches when a processing row is on screen
	pollTimer = setInterval(() => {
		if (rows.value.some((r) => r.status === "processing")) refreshKeep()
	}, 5000)
	document.addEventListener("visibilitychange", onVisibility)
})
onBeforeUnmount(() => {
	if (pollTimer) clearInterval(pollTimer)
	document.removeEventListener("visibilitychange", onVisibility)
})

// ── cell helpers ─────────────────────────────────────────────────────────────
function stripTitle(title) {
	return (title || "").replace(/^File: /, "")
}
</script>
