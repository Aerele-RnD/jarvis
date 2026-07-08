// useListPage - server-envelope list state for the v3 list kit (DESIGN-V3 §5.1).
// One instance per list page; feeds ListPage.vue. Wire format matches api.js
// `_page()` ({search, filters, sort_field, sort_dir, start, page_length})
// against the frozen envelope {rows, total, has_more, start, page_length[, facets]}.
// Ported behaviors from round-2 FeatureListPage: monotonic request id (stale
// responses dropped), errors keep last-good rows + toast, facets captured from
// page-1 responses.
import { ref, reactive, watch, onMounted, onBeforeUnmount } from "vue"
import { useStorage } from "@vueuse/core"
import { toast } from "frappe-ui"

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

export function useListPage({ fetchFn, defaultSort = { field: "", dir: "" }, storageKey, initialFilters = {} }) {
	const rows = ref([])
	const total = ref(0)
	const hasMore = ref(false)
	const loading = ref(false)
	const error = ref("")
	const facets = ref({})

	const search = ref("")
	const filters = reactive({})
	for (const [k, v] of Object.entries(initialFilters || {})) {
		if (v !== "" && v != null) filters[k] = v
	}
	const sort = ref({ field: defaultSort.field || "", dir: defaultSort.dir || "" })
	const pageLength = useStorage(`jarvis-pl-${storageKey}`, 20)

	// monotonic request id - drops stale responses (same guard as ChatView.loadConversation)
	let reqId = 0

	// mode: "reset" (page 1, replaces rows) | "more" (start=rows.length, appends)
	//     | "keep"  (silent refetch of the loaded window 0..min(rows.length,100))
	async function fetchRows(mode = "reset") {
		if (!fetchFn) return
		const id = ++reqId
		const append = mode === "more"
		const pl =
			mode === "keep"
				? Math.min(Math.max(rows.value.length || pageLength.value, 1), 100)
				: pageLength.value
		if (mode !== "keep") loading.value = true
		try {
			const res =
				(await fetchFn({
					search: search.value.trim(),
					filters: { ...filters },
					sort_field: sort.value.field || "",
					sort_dir: sort.value.dir || "",
					start: append ? rows.value.length : 0,
					page_length: pl,
				})) || {}
			if (id !== reqId) return // stale - a newer request superseded this one
			const nr = res.rows || []
			rows.value = append ? [...rows.value, ...nr] : nr
			total.value = res.total != null ? res.total : rows.value.length
			hasMore.value = res.has_more != null ? !!res.has_more : rows.value.length < total.value
			if (!append && res.facets) facets.value = res.facets
			error.value = ""
		} catch (e) {
			if (id !== reqId) return
			error.value = errMsg(e) // keep last-good rows visible
			toast.error(error.value)
		} finally {
			if (id === reqId) loading.value = false
		}
	}

	function resetLoad() {
		return fetchRows("reset")
	}
	function loadMore() {
		if (!hasMore.value || loading.value) return
		return fetchRows("more")
	}
	function refreshKeep() {
		return fetchRows("keep")
	}

	function setFilter(key, value) {
		if (value === "" || value == null) delete filters[key]
		else filters[key] = value
		return resetLoad()
	}
	// Replace the whole filter set (ListPage's update:filters emits a plain
	// object); empty values are stripped so the backend's strict key/value
	// whitelists never see blanks.
	function setFilters(next) {
		for (const k of Object.keys(filters)) delete filters[k]
		for (const [k, v] of Object.entries(next || {})) {
			if (v !== "" && v != null) filters[k] = v
		}
		return resetLoad()
	}
	function setSort(field, dir) {
		sort.value = { field: field || "", dir: dir || "" }
		return resetLoad()
	}

	// search debounced 300ms → resetLoad
	let searchTimer = null
	watch(search, () => {
		clearTimeout(searchTimer)
		searchTimer = setTimeout(() => resetLoad(), 300)
	})
	// page-length switch resets to page 1 (D16)
	watch(pageLength, () => resetLoad())

	onMounted(() => resetLoad())
	onBeforeUnmount(() => clearTimeout(searchTimer))

	return {
		rows,
		total,
		hasMore,
		loading,
		error,
		facets,
		search,
		filters,
		setFilter,
		setFilters,
		sort,
		setSort,
		pageLength,
		resetLoad,
		loadMore,
		refreshKeep,
	}
}
