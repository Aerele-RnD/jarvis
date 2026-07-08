<template>
	<section class="flex flex-col rounded-lg border p-4">
		<!-- header: title + adaptive copy left, SM process-now top-right -->
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0">
				<div class="text-base font-semibold text-ink-gray-9">My notes</div>
				<div class="mt-0.5 text-sm text-ink-gray-6">
					<!-- the Review tab is SM-only; pointing everyone at it is a dead end -->
					<template v-if="canProcess">
						Notes you've saved. Usually processed within a day - proposals show
						up on the Review tab; wiki context may update sooner.
					</template>
					<template v-else>
						Notes you've saved. Jarvis usually works them into its org knowledge
						within a day - wiki pages may update sooner.
					</template>
				</div>
			</div>
			<Button
				v-if="canProcess"
				class="shrink-0"
				variant="subtle"
				label="Process notes now"
				iconLeft="play"
				:loading="processing"
				@click="confirmProcessNow"
			/>
		</div>

		<!-- SM-only sweep telemetry (the old Processing card's status lines) -->
		<div v-if="canProcess" class="mt-2 flex flex-col gap-0.5 text-sm">
			<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
				<span class="text-ink-gray-5">Last processed:</span>
				<Tooltip v-if="lastProcessedAt" :text="exactDate(lastProcessedAt)">
					<span class="text-ink-gray-8">{{ timeAgo(lastProcessedAt) }}</span>
				</Tooltip>
				<span v-else class="text-ink-gray-6">never</span>
				<template v-if="orgNewNotes != null">
					<span class="text-ink-gray-4">·</span>
					<span class="text-ink-gray-6">
						{{ orgNewNotes }} new note{{ orgNewNotes === 1 ? "" : "s" }} org-wide
					</span>
				</template>
			</div>
			<div v-if="lastProcessStatus" class="text-ink-gray-6">
				{{ lastProcessStatus }}
			</div>
		</div>

		<!-- search + status filter -->
		<div class="mt-3 flex items-center gap-2">
			<FormControl
				type="text"
				class="min-w-0 flex-1"
				placeholder="Search notes"
				:modelValue="search"
				@update:modelValue="(v) => (search = v)"
			>
				<template #prefix>
					<FeatherIcon name="search" class="size-4 text-ink-gray-5" />
				</template>
			</FormControl>
			<FormControl
				type="select"
				class="w-32 shrink-0"
				:options="STATUS_OPTIONS"
				:modelValue="statusFilter"
				@update:modelValue="(v) => (statusFilter = v)"
			/>
		</div>

		<!-- list -->
		<div v-if="notes.loading && !notes.rows.length" class="py-8 text-center">
			<LoadingIndicator class="size-5 text-ink-gray-5" />
		</div>
		<div
			v-else-if="!notes.rows.length && filtered"
			class="mt-3 flex flex-col items-center gap-1 rounded-lg border border-dashed py-10 text-center"
		>
			<FeatherIcon name="search" class="size-6 text-ink-gray-5" />
			<span class="mt-1 text-base font-medium text-ink-gray-8">No matching notes</span>
			<span class="text-p-base text-ink-gray-6">
				Try a different search or status filter.
			</span>
		</div>
		<div
			v-else-if="!notes.rows.length"
			class="mt-3 flex flex-col items-center gap-1 rounded-lg border border-dashed py-10 text-center"
		>
			<FeatherIcon name="mic" class="size-6 text-ink-gray-5" />
			<span class="mt-1 text-base font-medium text-ink-gray-8">No notes yet</span>
			<span class="text-p-base text-ink-gray-6">
				Record or type your first note.
			</span>
		</div>
		<div v-else class="mt-2 divide-y">
			<div
				v-for="row in notes.rows"
				:key="row.name"
				class="flex items-start justify-between gap-3 py-3"
			>
				<div class="min-w-0 flex-1">
					<p class="line-clamp-2 text-sm text-ink-gray-8">
						{{ row.excerpt || row.transcript }}
					</p>
					<div class="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink-gray-5">
						<Tooltip :text="exactDate(row.creation)">
							<span>{{ timeAgo(row.creation) }}</span>
						</Tooltip>
						<Badge
							variant="subtle"
							:theme="NOTE_THEME[row.status] || 'gray'"
							:label="row.status"
						/>
						<span v-if="row.context_type === 'Conversation'">· from chat</span>
					</div>
				</div>
				<div class="flex shrink-0 items-center">
					<!-- only New notes are editable - the edited transcript re-feeds
					     the daily sweep; Processed/Archived text is already consumed -->
					<Button
						v-if="row.status === 'New'"
						variant="ghost"
						icon="edit-2"
						:tooltip="'Edit note'"
						@click="openEdit(row)"
					/>
					<Button
						variant="ghost"
						icon="trash-2"
						:tooltip="'Delete note'"
						:loading="deleting === row.name"
						:disabled="!!deleting"
						@click="confirmDeleteNote(row)"
					/>
				</div>
			</div>
		</div>

		<div v-if="notes.hasMore" class="mt-2 flex justify-center">
			<Button
				variant="subtle"
				label="Load more"
				:loading="notes.loading"
				@click="fetchNotes('more')"
			/>
		</div>

		<!-- edit dialog (New notes only) -->
		<Dialog v-model="editDialog.show" :options="{ title: 'Edit note', size: 'lg' }">
			<template #body-content>
				<FormControl
					type="textarea"
					:rows="8"
					:modelValue="editDialog.text"
					@update:modelValue="(v) => (editDialog.text = v)"
				/>
				<p class="mt-1.5 text-p-sm text-ink-gray-5">
					The edited note replaces the original and is processed in the next
					daily run.
				</p>
				<div class="mt-4 flex items-center gap-2">
					<Button
						variant="solid"
						label="Save"
						:loading="editDialog.saving"
						:disabled="!editDialog.text.trim()"
						@click="saveEdit"
					/>
					<Button label="Cancel" @click="editDialog.show = false" />
				</div>
			</template>
		</Dialog>
	</section>
</template>

<script setup>
// NotesPane - the right pane of the Business tab: the caller's own voice
// notes with server-side search (300ms debounce), a status filter, real
// Load More pagination, edit-while-New and delete. For System Managers the
// old Processing card collapses into this pane's header: "Process notes now"
// top-right plus the last-sweep telemetry line (the parent feeds those via
// props from get_business_status and refreshes them on @changed).
// Parent contract: props below; emits "changed" after any mutation the
// status card cares about (edit/delete/process); exposes reload() so the
// parent can reset the list after saving a new note or on header refresh.
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from "vue"
import {
	Badge,
	Button,
	Dialog,
	FeatherIcon,
	FormControl,
	LoadingIndicator,
	Tooltip,
	toast,
	confirmDialog,
} from "frappe-ui"
import { timeAgo, exactDate } from "@/utils/datetime"
import {
	listMyVoiceNotesPage,
	updateVoiceNote,
	deleteVoiceNote,
	processVoiceNotesNow,
} from "@/api/voice"

const props = defineProps({
	canProcess: { type: Boolean, default: false },
	lastProcessedAt: { type: String, default: "" },
	lastProcessStatus: { type: String, default: "" },
	orgNewNotes: { type: Number, default: null },
})
const emit = defineEmits(["changed"])

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

const NOTE_THEME = { New: "blue", Processed: "green", Archived: "gray" }
const STATUS_OPTIONS = [
	{ label: "All", value: "" },
	{ label: "New", value: "New" },
	{ label: "Processed", value: "Processed" },
	{ label: "Archived", value: "Archived" },
]

// ── state ────────────────────────────────────────────────────────────────────
const search = ref("")
const statusFilter = ref("")
const notes = reactive({ rows: [], total: 0, hasMore: false, loading: false })
const deleting = ref("")
const processing = ref(false)
const editDialog = reactive({ show: false, name: "", text: "", saving: false })

const filtered = computed(() => !!(search.value.trim() || statusFilter.value))

// ── loader ───────────────────────────────────────────────────────────────────
// monotonic request id - drops stale responses (the useListPage idiom): the
// debounced search fetch, the immediate status-filter fetch and the parent's
// reload() can be in flight at once; only the newest may render.
let reqId = 0

async function fetchNotes(mode = "reset") {
	const id = ++reqId
	const append = mode === "more"
	notes.loading = true
	try {
		const res = await listMyVoiceNotesPage({
			start: append ? notes.rows.length : 0,
			page_length: 20,
			status: statusFilter.value || undefined,
			search: search.value.trim() || undefined,
		})
		if (id !== reqId) return // stale - a newer request superseded this one
		const rows = res.rows || []
		notes.rows = append ? [...notes.rows, ...rows] : rows
		notes.total = res.total || 0
		notes.hasMore = !!res.has_more
	} catch (e) {
		if (id !== reqId) return
		toast.error(errMsg(e))
	} finally {
		if (id === reqId) notes.loading = false
	}
}

function reload() {
	return fetchNotes("reset")
}
defineExpose({ reload })

// search debounced 300ms → reset (useListPage precedent); status is a select,
// so it resets immediately
let searchTimer = null
watch(search, () => {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => fetchNotes("reset"), 300)
})
watch(statusFilter, () => fetchNotes("reset"))
onBeforeUnmount(() => clearTimeout(searchTimer))

// ── edit (New notes only - server enforces owner + status) ───────────────────
function openEdit(row) {
	editDialog.name = row.name
	editDialog.text = row.transcript || row.excerpt || ""
	editDialog.saving = false
	editDialog.show = true
}

async function saveEdit() {
	const text = editDialog.text.trim()
	if (!text) return
	editDialog.saving = true
	try {
		await updateVoiceNote(editDialog.name, text)
		editDialog.show = false
		toast.success("Note updated")
		fetchNotes("reset")
		emit("changed")
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		editDialog.saving = false
	}
}

// ── delete ───────────────────────────────────────────────────────────────────
function confirmDeleteNote(row) {
	confirmDialog({
		title: "Delete this note?",
		message:
			row.status === "Processed"
				? "This removes the note from your list. Knowledge Jarvis already extracted from it is kept."
				: "This note hasn't been processed yet - Jarvis won't learn from it if you delete it now.",
		onConfirm: async ({ hideDialog }) => {
			await doDeleteNote(row)
			hideDialog()
		},
	})
}

async function doDeleteNote(row) {
	deleting.value = row.name
	try {
		await deleteVoiceNote(row.name)
		toast.success("Note deleted")
		fetchNotes("reset")
		emit("changed")
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		deleting.value = ""
	}
}

// ── processing (SM) ──────────────────────────────────────────────────────────
function confirmProcessNow() {
	confirmDialog({
		title: "Process voice notes now?",
		message:
			"Runs LLM processing over all new voice notes immediately instead of waiting for the daily run. Extracted rules appear as proposals on the Review tab; context goes into the org wiki.",
		onConfirm: async ({ hideDialog }) => {
			processing.value = true
			try {
				const r = await processVoiceNotesNow()
				hideDialog()
				if (r && r.ok === false) {
					toast.error(r.reason || "Could not start processing.")
				} else {
					toast.success("Processing started")
				}
				fetchNotes("reset")
				emit("changed")
			} catch (e) {
				toast.error(errMsg(e))
			} finally {
				processing.value = false
			}
		},
	})
}

// ── init ─────────────────────────────────────────────────────────────────────
onMounted(() => fetchNotes("reset"))
</script>
