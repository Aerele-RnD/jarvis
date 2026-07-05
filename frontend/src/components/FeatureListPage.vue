<template>
	<div class="fp-listpage">
		<!-- ── toolbar: search + filters + header actions ── -->
		<div class="fp-toolbar">
			<div class="fp-search">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
				<input v-model="search" :placeholder="searchConfig && searchConfig.placeholder ? searchConfig.placeholder : 'Search'" />
			</div>
			<template v-for="f in filtersConfig" :key="f.key">
				<select v-if="f.type === 'select'" class="fp-in fp-filter" v-model="filterValues[f.key]" :title="f.label">
					<option v-for="o in f.options" :key="String(o.value)" :value="o.value">{{ o.label }}</option>
				</select>
				<span v-else-if="f.type === 'daterange'" class="fp-daterange">
					<input type="date" class="fp-in" v-model="filterValues[f.key].from_date" :title="(f.label || 'Date') + ' — from'" />
					<span class="fp-daterange-sep">–</span>
					<input type="date" class="fp-in" v-model="filterValues[f.key].to_date" :title="(f.label || 'Date') + ' — to'" />
				</span>
			</template>
			<div style="flex:1;"></div>
			<slot name="toolbar" />
			<button v-for="a in headerActions" :key="a.id" class="fp-btn fp-btn--sm" :class="{ 'fp-btn--primary': a.primary, 'fp-btn--danger': a.danger }" @click="a.onClick">{{ a.label }}</button>
		</div>

		<!-- ── inline banner slot ── -->
		<slot name="banner" />

		<!-- ── error banner (last-good rows kept underneath) ── -->
		<div v-if="error" class="fp-err">{{ error }}</div>

		<!-- ── list ── -->
		<div class="fp-list" role="table">
			<!-- header row -->
			<div class="fp-list-head" role="row" :style="{ gridTemplateColumns: gridTemplate }">
				<div v-if="selectable" class="fp-cell fp-cell--check">
					<input type="checkbox" :checked="allSelected" :indeterminate.prop="someSelected" @change="toggleAll" aria-label="Select all" />
				</div>
				<div v-for="c in columns" :key="c.key" class="fp-cell fp-hcell" :class="[alignClass(c), { sortable: isSortable(c.key) }]" @click="isSortable(c.key) && toggleSort(c.key)">
					<span>{{ c.label }}</span>
					<span v-if="isSortable(c.key)" class="fp-sort" :class="sortState(c.key)">
						<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 15 6-6 6 6" /></svg>
					</span>
				</div>
				<div v-if="hasRowActions" class="fp-cell fp-cell--actions"></div>
			</div>

			<!-- skeletons (page-1 loads only) -->
			<template v-if="loading">
				<div v-for="n in skeletonCount" :key="'sk' + n" class="fp-list-row fp-skel-row" :style="{ gridTemplateColumns: gridTemplate }">
					<div v-if="selectable" class="fp-cell fp-cell--check"></div>
					<div v-for="c in columns" :key="c.key" class="fp-cell" :class="alignClass(c)"><span class="fp-skel"></span></div>
					<div v-if="hasRowActions" class="fp-cell fp-cell--actions"></div>
				</div>
			</template>

			<!-- empty state -->
			<div v-else-if="!rows.length" class="fp-empty">
				<b>{{ emptyState && emptyState.title ? emptyState.title : "Nothing here yet." }}</b>
				<span v-if="emptyState && emptyState.description">{{ emptyState.description }}</span>
			</div>

			<!-- rows -->
			<template v-else>
				<template v-for="row in rows" :key="rowKeyOf(row)">
					<div class="fp-list-row" :class="{ clickable: isRowClickable, selected: isSelected(row), expanded: isExpanded(row) }" :style="{ gridTemplateColumns: gridTemplate }" @click="onRowClickInternal(row)">
						<div v-if="selectable" class="fp-cell fp-cell--check" @click.stop>
							<input type="checkbox" :checked="isSelected(row)" @change="toggleRow(row)" :aria-label="'Select ' + rowKeyOf(row)" />
						</div>
						<div v-for="c in columns" :key="c.key" class="fp-cell" :class="alignClass(c)">
							<slot :name="'cell-' + c.key" :row="row" :value="row[c.key]">{{ formatCell(c, row) }}</slot>
						</div>
						<div v-if="hasRowActions" class="fp-cell fp-cell--actions" @click.stop>
							<button v-for="act in rowActionsFor(row)" :key="act.id" class="fp-iconbtn" :class="{ danger: act.danger }" :disabled="act.disabled" :title="act.title || act.label" @click="act.onClick(row)">
								<span v-if="act.icon" class="fp-iconbtn-ic" v-html="act.icon"></span>
								<span v-else>{{ act.label }}</span>
							</button>
						</div>
					</div>
					<div v-if="expandable && isExpanded(row)" class="fp-row-expand">
						<slot name="row-expand" :row="row" />
					</div>
				</template>
			</template>
		</div>

		<!-- ── footer: page-length + Load More + count (ListFooter parity) ── -->
		<div v-if="!loading && rows.length" class="fp-footer">
			<div class="fp-pagelen" role="group" aria-label="Rows per page">
				<button v-for="opt in PAGE_LENGTHS" :key="opt" class="fp-pagelen-btn" :class="{ on: pageLength === opt }" @click="setPageLength(opt)">{{ opt }}</button>
			</div>
			<div style="flex:1;"></div>
			<span class="fp-count">{{ rows.length }} of {{ total }}</span>
			<button v-if="hasMore" class="fp-btn fp-btn--sm fp-btn--ghost" :disabled="loadingMore" @click="loadMore">
				<span v-if="loadingMore" class="fp-spin"></span>
				{{ loadingMore ? "Loading…" : "Load more" }}
			</button>
		</div>

		<!-- ── floating bulk-selection banner ── -->
		<div v-if="selectable && selected.length" class="fp-bulkbar">
			<span class="fp-bulk-n">{{ selected.length }} selected</span>
			<button v-for="(b, i) in bulkActions" :key="i" class="fp-btn fp-btn--sm" :class="{ 'fp-btn--danger': b.danger }" @click="b.onClick([...selected])">{{ b.label }}</button>
			<button class="fp-btn fp-btn--sm fp-btn--ghost" @click="clearSelection">Clear</button>
		</div>
	</div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from "vue"
import { useNotify } from "@/composables/useNotify"
import "@/styles/fp.css"

const PAGE_LENGTHS = [20, 50, 100]
const { errMsg } = useNotify()

const props = defineProps({
	columns: { type: Array, default: () => [] }, // [{ key, label, width, align?, format? }]
	rowKey: { type: String, default: "name" },
	fetchFn: { type: Function, default: null }, // async (params) => {rows,total,has_more,start,page_length[,facets]}
	filtersConfig: { type: Array, default: () => [] }, // [{ key, label, type:"select"|"daterange", options, default? }]
	searchConfig: { type: Object, default: () => ({ placeholder: "Search", debounceMs: 300 }) },
	sortableKeys: { type: Array, default: () => [] },
	defaultSort: { type: Object, default: () => ({ field: "", dir: "" }) },
	rowActions: { type: Function, default: null }, // (row) => [{ id, label, icon?, danger?, disabled?, title?, onClick(row) }]
	onRowClick: { type: Function, default: null },
	headerActions: { type: Array, default: () => [] }, // [{ id, label, primary?, danger?, onClick }]
	selectable: { type: Boolean, default: false },
	bulkActions: { type: Array, default: () => [] }, // [{ label, danger?, onClick(selectedRowKeys) }]
	emptyState: { type: Object, default: () => ({}) }, // { title, description }
	expandable: { type: Boolean, default: false },
})
const emit = defineEmits(["state"])

// ── reactive query state ────────────────────────────────────────────────────
const search = ref("")
const filterValues = ref({})
const sortField = ref(props.defaultSort && props.defaultSort.field ? props.defaultSort.field : "")
const sortDir = ref(props.defaultSort && props.defaultSort.dir ? props.defaultSort.dir : "")
const pageLength = ref(20)

// ── results ─────────────────────────────────────────────────────────────────
const rows = ref([])
const total = ref(0)
const hasMore = ref(false)
const facets = ref({})
const loading = ref(false) // page-1 (skeleton) load
const loadingMore = ref(false) // Load More (inline spinner)
const error = ref("")

// ── selection / expansion ───────────────────────────────────────────────────
const selected = ref([]) // row keys
const expandedKey = ref(null)

// monotonic request id — drops stale responses (same guard as ChatView.loadConversation)
let reqId = 0
let searchTimer = null

// ── filter initialization ───────────────────────────────────────────────────
function initFilters() {
	const fv = {}
	for (const f of props.filtersConfig || []) {
		if (f.type === "daterange") fv[f.key] = { from_date: "", to_date: "" }
		else fv[f.key] = f.default != null ? f.default : ""
	}
	filterValues.value = fv
}
function buildFilters() {
	const out = {}
	for (const f of props.filtersConfig || []) {
		if (f.type === "daterange") {
			const v = filterValues.value[f.key] || {}
			if (v.from_date) out.from_date = v.from_date
			if (v.to_date) out.to_date = v.to_date
		} else {
			const v = filterValues.value[f.key]
			if (v !== "" && v != null) out[f.key] = v
		}
	}
	return out
}
// Seed filter values BEFORE the deep watcher below is registered, so the initial
// assignment does not count as a change (which would double-fetch on mount).
initFilters()

// ── fetch ────────────────────────────────────────────────────────────────────
// mode: "reset" (page-1 skeleton load, clears selection/expansion)
//     | "more"  (Load More; appends)
//     | "keep"  (silent refresh of the currently-loaded window; ≤100 rows)
async function fetchRows(mode = "reset") {
	if (!props.fetchFn) return
	const id = ++reqId
	const append = mode === "more"
	const startOffset = append ? rows.value.length : 0
	// "keep" re-requests the currently-loaded span in one page (server clamps ≤100).
	const pl = mode === "keep" ? Math.min(Math.max(rows.value.length || pageLength.value, 1), 100) : pageLength.value
	if (append) loadingMore.value = true
	else if (mode === "reset") loading.value = true
	try {
		const res = (await props.fetchFn({
			search: search.value.trim(),
			filters: buildFilters(),
			sort_field: sortField.value,
			sort_dir: sortDir.value,
			start: startOffset,
			page_length: pl,
		})) || {}
		if (id !== reqId) return // stale — a newer request superseded this one
		const nr = res.rows || []
		rows.value = append ? [...rows.value, ...nr] : nr
		total.value = res.total != null ? res.total : rows.value.length
		hasMore.value = res.has_more != null ? !!res.has_more : rows.value.length < total.value
		facets.value = res.facets || {}
		error.value = ""
		if (mode === "reset") {
			selected.value = []
			expandedKey.value = null
		} else {
			// prune selection/expansion to rows still present
			const present = new Set(rows.value.map(rowKeyOf))
			selected.value = selected.value.filter((k) => present.has(k))
			if (expandedKey.value != null && !present.has(expandedKey.value)) expandedKey.value = null
		}
	} catch (e) {
		if (id !== reqId) return
		error.value = errMsg(e) // keep last-good rows visible
	} finally {
		if (id === reqId) {
			loading.value = false
			loadingMore.value = false
		}
	}
}

function emitState() {
	emit("state", {
		search: search.value.trim(),
		filters: buildFilters(),
		sort_field: sortField.value,
		sort_dir: sortDir.value,
	})
}
function resetAndFetch() {
	emitState()
	fetchRows("reset")
}

// ── change handlers ──────────────────────────────────────────────────────────
watch(search, () => {
	clearTimeout(searchTimer)
	const ms = props.searchConfig && props.searchConfig.debounceMs != null ? props.searchConfig.debounceMs : 300
	searchTimer = setTimeout(() => resetAndFetch(), ms)
})
watch(filterValues, () => resetAndFetch(), { deep: true })
watch([sortField, sortDir], () => resetAndFetch())

function setPageLength(opt) {
	if (opt === pageLength.value) return
	pageLength.value = opt
	resetAndFetch()
}
function loadMore() {
	if (!hasMore.value || loadingMore.value) return
	fetchRows("more")
}

// ── sorting (asc → desc → default) ──────────────────────────────────────────
function isSortable(key) {
	return (props.sortableKeys || []).includes(key)
}
function sortState(key) {
	return sortField.value === key ? sortDir.value : ""
}
function toggleSort(key) {
	if (!isSortable(key)) return
	if (sortField.value !== key) {
		sortField.value = key
		sortDir.value = "asc"
	} else if (sortDir.value === "asc") {
		sortDir.value = "desc"
	} else {
		// back to default
		sortField.value = props.defaultSort && props.defaultSort.field ? props.defaultSort.field : ""
		sortDir.value = props.defaultSort && props.defaultSort.dir ? props.defaultSort.dir : ""
	}
}

// ── selection ────────────────────────────────────────────────────────────────
function rowKeyOf(row) {
	return row[props.rowKey]
}
function isSelected(row) {
	return selected.value.includes(rowKeyOf(row))
}
function toggleRow(row) {
	const k = rowKeyOf(row)
	selected.value = selected.value.includes(k) ? selected.value.filter((x) => x !== k) : [...selected.value, k]
}
const allSelected = computed(() => rows.value.length > 0 && rows.value.every((r) => selected.value.includes(rowKeyOf(r))))
const someSelected = computed(() => selected.value.length > 0 && !allSelected.value)
function toggleAll() {
	if (allSelected.value) selected.value = []
	else selected.value = rows.value.map(rowKeyOf)
}
function clearSelection() {
	selected.value = []
}

// ── expansion / row click ────────────────────────────────────────────────────
const isRowClickable = computed(() => props.expandable || !!props.onRowClick)
function isExpanded(row) {
	return props.expandable && expandedKey.value === rowKeyOf(row)
}
function onRowClickInternal(row) {
	if (props.expandable) {
		const k = rowKeyOf(row)
		expandedKey.value = expandedKey.value === k ? null : k
	} else if (props.onRowClick) {
		props.onRowClick(row)
	}
}

// ── cell / column helpers ────────────────────────────────────────────────────
const hasRowActions = computed(() => !!props.rowActions)
function rowActionsFor(row) {
	return props.rowActions ? props.rowActions(row) || [] : []
}
function formatCell(c, row) {
	const v = row[c.key]
	return c.format ? c.format(v, row) : v != null ? v : ""
}
function alignClass(c) {
	return c.align === "right" ? "fp-cell--right" : c.align === "center" ? "fp-cell--center" : ""
}
// grid template mirrors frappe-ui getGridTemplateColumns (utils.js): numeric
// width → fr, string passthrough; a 14px checkbox column prepended when
// selectable, and a fixed trailing actions column so columns stay aligned
// across rows regardless of how many action buttons a given row renders.
function colWidth(w) {
	if (w == null) return "minmax(0, 1fr)"
	return typeof w === "number" ? `minmax(0, ${w}fr)` : w
}
const gridTemplate = computed(() => {
	const parts = []
	if (props.selectable) parts.push("14px")
	for (const c of props.columns) parts.push(colWidth(c.width))
	if (hasRowActions.value) parts.push("96px")
	return parts.join(" ")
})

const skeletonCount = computed(() => Math.min(pageLength.value, 8))

// ── public API (expose) ──────────────────────────────────────────────────────
// refresh({ keepPage }): keepPage=true silently re-reads the current window
// (Files processing-poll / visibilitychange); default reloads page 1.
function refresh({ keepPage = false } = {}) {
	return keepPage ? fetchRows("keep") : fetchRows("reset")
}
defineExpose({ refresh, rows, total, loading })

// ── lifecycle ────────────────────────────────────────────────────────────────
onMounted(() => {
	fetchRows("reset")
})
onBeforeUnmount(() => clearTimeout(searchTimer))
</script>
