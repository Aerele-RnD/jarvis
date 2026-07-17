<template>
	<div class="flex flex-col">
		<div class="px-5 pt-4">
			<div class="text-base font-semibold text-ink-gray-9">Analysis runs</div>
			<div class="mt-0.5 text-sm text-ink-gray-6">
				Every app analysis ever scheduled on this bench, newest first.
			</div>
		</div>

		<!-- embedded ListPage (show-header=false: AnalysisTab owns the page's
		     LayoutHeader). min-h only when empty/errored - those states are
		     absolutely positioned inside a flex-1 box that otherwise collapses
		     to zero height outside a full-height page. -->
		<ListPage
			:class="rows.length ? '' : 'min-h-[20rem]'"
			:show-header="false"
			:columns="columns"
			:rows="rows"
			:loading="loading"
			:error="error"
			:total="total"
			:has-more="hasMore"
			:quick-filters="quickFilters"
			:filter-defs="filterDefs"
			:filters="filters"
			:sort-options="sortOptions"
			:sort="sort"
			:page-length="pageLength"
			:default-sort="DEFAULT_SORT"
			:selectable="false"
			:on-row-click="openRow"
			storage-key="app-learning-runs"
			:empty-state="emptyState"
			@update:filters="setFilters"
			@update:sort="(s) => setSort(s.field, s.dir)"
			@update:page-length="(v) => (pageLength = v)"
			@load-more="loadMore"
			@refresh="resetLoad"
		>
			<template #cell-status="{ row }">
				<Tooltip v-if="row.status === 'Failed' && row.error" :text="errorPreview(row)">
					<Badge variant="subtle" theme="red" :label="row.status" />
				</Tooltip>
				<Badge
					v-else
					variant="subtle"
					:theme="STATUS_THEME[row.status] || 'gray'"
					:label="row.status || '-'"
				/>
			</template>

			<template #cell-app="{ row }">
				<div class="truncate text-base font-medium text-ink-gray-8">{{ row.app }}</div>
			</template>

			<template #cell-progress="{ row }">
				<div class="truncate text-base text-ink-gray-7">
					{{ row.batches_total ? `${row.batches_done || 0}/${row.batches_total}` : "-" }}
				</div>
			</template>

			<template #cell-pages_written="{ row }">
				<div class="truncate text-base text-ink-gray-7">
					{{ row.pages_written != null ? row.pages_written : "-" }}
				</div>
			</template>

			<template #cell-skills_created="{ row }">
				<div class="truncate text-base text-ink-gray-7">
					{{ row.skills_created != null ? row.skills_created : "-"
					}}<span v-if="row.skills_deferred > 0" class="text-ink-gray-5">
						({{ row.skills_deferred }} deferred)</span
					>
				</div>
			</template>

			<template #cell-requested_by="{ row }">
				<div class="truncate text-base text-ink-gray-7">{{ row.requested_by || "-" }}</div>
			</template>

			<template #cell-finished_at="{ row }">
				<Tooltip v-if="row.finished_at" :text="exactDate(row.finished_at)">
					<div class="truncate text-base">{{ timeAgo(row.finished_at) }}</div>
				</Tooltip>
				<span v-else class="text-base text-ink-gray-4">-</span>
			</template>

			<template #cell-duration="{ row }">
				<div class="truncate text-base text-ink-gray-7">{{ durationLabel(row) }}</div>
			</template>

			<template #cell-_actions="{ row }">
				<div class="flex w-full items-center justify-end gap-1" @click.stop.prevent>
					<!-- Ingesting is deliberately NOT cancellable (backend
					     _CANCELLABLE): findings are mid-write by then -->
					<Button
						v-if="CANCELLABLE.includes(row.status)"
						variant="ghost"
						theme="red"
						icon="x-circle"
						label="Cancel run"
						:tooltip="'Cancel run'"
						:loading="cancelling === row.name"
						@click="cancelRun(row)"
					/>
					<Button
						v-if="row.conversation"
						variant="ghost"
						icon="message-circle"
						label="View conversation"
						:tooltip="'View conversation'"
						@click="router.push('/c/' + row.conversation)"
					/>
					<Button
						v-if="row.status === 'Failed' && row.error"
						variant="ghost"
						theme="red"
						icon="alert-circle"
						label="Show error"
						:tooltip="'Show error'"
						@click="showError(row)"
					/>
				</div>
			</template>
		</ListPage>

		<!-- full error text for Failed rows (the badge tooltip only previews it) -->
		<Dialog v-model="errorDialog.show" :options="{ title: 'Run failed', size: 'lg' }">
			<template #body-content>
				<p class="text-sm text-ink-gray-6">
					Full error from the analysis run for
					<span class="font-medium text-ink-gray-8">{{ errorDialog.app }}</span
					>:
				</p>
				<pre
					class="mt-3 max-h-96 overflow-y-auto whitespace-pre-wrap rounded bg-surface-gray-2 p-2 font-mono text-sm text-ink-gray-8"
					>{{ errorDialog.text }}</pre
				>
			</template>
			<template #actions>
				<div class="flex items-center gap-2">
					<Button label="Close" @click="errorDialog.show = false" />
				</div>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
// AppLearningRunsList - the app-learning run history inside the "Learn from
// custom apps" card (AnalysisTab). Standard v3 list kit: ListPage (embedded,
// show-header=false) + useListPage against
// jarvis.chat.app_learning_api.list_app_learning_runs_page. Search + status
// quick filter, app/status FilterButton defs, creation/app/status/finished_at
// sort, load-more pagination, column show/hide persisted under
// "app-learning-runs". Row actions: Cancel (non-terminal, confirm), View
// conversation, full-error dialog on Failed rows. Row click opens the run's
// conversation (the macros RunsTab manner). The card above owns the realtime
// socket + overview; it drives this list through the exposed reload()/
// refresh() and listens for `changed` (a cancel here also moves overview
// state - active-run strip, per-app chips).
import { computed, reactive, ref } from "vue"
import { useRouter } from "vue-router"
import { Badge, Button, Dialog, Tooltip, confirmDialog, dayjsLocal, toast } from "frappe-ui"
import ListPage from "@/components/list/ListPage.vue"
import { useListPage } from "@/composables/useListPage"
import { timeAgo, exactDate } from "@/utils/datetime"
import { cancelAppLearningRun, listAppLearningRunsPage } from "@/api/appLearning"

const props = defineProps({
	// [{label, value}] of installed apps (from the overview) for the App filter
	appOptions: { type: Array, default: () => [] },
})
const emit = defineEmits(["changed"])

const router = useRouter()

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

// ── list config ──────────────────────────────────────────────────────────────
// cancel_app_learning_run accepts these three only - an Ingesting run is
// already writing findings and must finish or fail
const CANCELLABLE = ["Queued", "Zipping", "Analyzing"]
// design.md §3.6 status→theme map: terminal per spec (Completed green /
// Failed red / Cancelled gray); Queued pending-orange, in-flight states blue.
const STATUS_THEME = {
	Queued: "orange",
	Zipping: "blue",
	Analyzing: "blue",
	Ingesting: "blue",
	Completed: "green",
	Failed: "red",
	Cancelled: "gray",
}
const STATUS_OPTIONS = [
	{ label: "All statuses", value: "" },
	{ label: "Queued", value: "Queued" },
	{ label: "Zipping", value: "Zipping" },
	{ label: "Analyzing", value: "Analyzing" },
	{ label: "Ingesting", value: "Ingesting" },
	{ label: "Completed", value: "Completed" },
	{ label: "Failed", value: "Failed" },
	{ label: "Cancelled", value: "Cancelled" },
]

const columns = [
	{ label: "Status", key: "status", width: "7rem" },
	{ label: "App", key: "app", width: 2 },
	{ label: "Progress", key: "progress", width: "6rem" },
	{ label: "Pages", key: "pages_written", width: "5rem" },
	{ label: "Skills", key: "skills_created", width: "8rem" },
	{ label: "Requested by", key: "requested_by", width: 2 },
	{ label: "Finished", key: "finished_at", width: "7rem" },
	{ label: "Duration", key: "duration", width: "6rem" },
	{ label: "", key: "_actions", width: "8rem", align: "right" },
]

// search rides the quick strip (the ActivityTab manner - the fetchFn below
// lifts it out of the filters object into the envelope's `search` arg).
const quickFilters = computed(() => [
	{ key: "search", label: "Search runs", type: "text" },
	{ key: "status", label: "Status", type: "select", options: STATUS_OPTIONS },
])
// FilterButton builds select/daterange rows only (DESIGN-V3 §5.3 D14), so the
// spec's "app (text)" lands as an equals-select over the bench's installed
// apps - exact matching either way, and free text still works via search.
const filterDefs = computed(() => [
	{
		key: "app",
		label: "App",
		type: "select",
		options: [{ label: "All apps", value: "" }, ...props.appOptions],
	},
	{ key: "status", label: "Status", type: "select", options: STATUS_OPTIONS },
])

// backend sortable whitelist: creation · app · status · finished_at
const sortOptions = [
	{ label: "Created", value: "creation" },
	{ label: "App", value: "app" },
	{ label: "Status", value: "status" },
	{ label: "Finished", value: "finished_at" },
]
const DEFAULT_SORT = { field: "creation", dir: "desc" }

const {
	rows,
	total,
	hasMore,
	loading,
	error,
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
		const { search: q, ...rest } = p.filters || {}
		return listAppLearningRunsPage({ ...p, search: q || p.search || "", filters: rest })
	},
	defaultSort: DEFAULT_SORT,
	storageKey: "app-learning-runs",
})

// zero rows reads differently under an active search/filter (the AgentsList /
// ReviewTab decided-log empty-state pattern): "no matches" vs the true blank
// slate. All active criteria live in `filters` - the search quick filter rides
// it too (key "search"), and setFilters strips empty values, so any key
// present means something is narrowing the list.
const filtersActive = computed(() => Object.keys(filters).length > 0)
const emptyState = computed(() =>
	filtersActive.value
		? {
				icon: "search",
				title: "No runs match",
				description: "Try clearing the search or filters.",
			}
		: {
				icon: "package",
				title: "No analysis runs yet",
				description: "Runs appear here once you analyze a custom app.",
			}
)

// reload = hard reset to page 1 (after user actions); refresh = silent
// refetch of the loaded window (realtime frames) - both driven by the card.
defineExpose({ reload: resetLoad, refresh: refreshKeep })

// ── row actions ──────────────────────────────────────────────────────────────
const cancelling = ref("")

function cancelRun(row) {
	confirmDialog({
		title: "Cancel this analysis run?",
		message: `Stops the ${row.status === "Queued" ? "queued" : "active"} analysis run for ${row.app}. You can schedule it again later from the checklist above.`,
		onConfirm: async ({ hideDialog }) => {
			cancelling.value = row.name
			try {
				await cancelAppLearningRun(row.name)
				hideDialog()
				toast.success("Run cancelled")
				resetLoad()
				emit("changed")
			} catch (e) {
				toast.error(errMsg(e))
			} finally {
				cancelling.value = ""
			}
		},
	})
}

function openRow(row) {
	if (row.conversation) router.push("/c/" + row.conversation)
}

const errorDialog = reactive({ show: false, app: "", text: "" })
function showError(row) {
	errorDialog.app = row.app || ""
	errorDialog.text = row.error || ""
	errorDialog.show = true
}
function errorPreview(row) {
	const t = String(row.error || "")
	return t.length > 160 ? t.slice(0, 160) + "…" : t
}

// ── formatters ───────────────────────────────────────────────────────────────
// finished - started, humanized (the macros RunsTab recipe). Both stamps are
// naive site-tz strings, so the tz-safe dayjsLocal diff cancels the offset.
function durationLabel(row) {
	if (!row.started_at || !row.finished_at) return "-"
	const sec = dayjsDiffSeconds(row.started_at, row.finished_at)
	if (sec == null || sec < 0) return "-"
	if (sec < 60) return `${sec}s`
	const m = Math.floor(sec / 60)
	const s = sec % 60
	if (m < 60) return s ? `${m}m ${s}s` : `${m}m`
	const h = Math.floor(m / 60)
	return `${h}h ${m % 60}m`
}
function dayjsDiffSeconds(a, b) {
	const start = dayjsLocalSafe(a)
	const end = dayjsLocalSafe(b)
	if (!start || !end) return null
	return end.diff(start, "second")
}
function dayjsLocalSafe(d) {
	try {
		const dj = dayjsLocal(String(d))
		return dj && typeof dj.isValid === "function" && dj.isValid() ? dj : null
	} catch (e) {
		return null
	}
}
</script>
