<template>
	<div class="kg flex h-full flex-col overflow-hidden">
		<div class="kg-head">
			<h5>Knowledge Graph</h5>
			<span v-if="state.loaded && pageCount" class="text-muted">{{ pageCount }} pages · {{ linkCount }} links</span>
			<Button class="kg-desk" variant="outline" size="sm" icon="external-link"
				:tooltip="'Open ERPNext Desk'" @click="openDesk" />
		</div>

		<div v-if="!state.loaded" class="kg-skel"></div>
		<div v-else-if="state.error" class="kg-err">
			{{ state.error }} <button class="kg-btn" @click="load">Retry</button>
		</div>
		<div v-else-if="!rawPageCount" class="kg-empty text-muted">
			<i>No wiki pages yet — create some under the Wiki tab, then come back to
			connect and explore them here.</i>
		</div>

		<div v-else class="kg-layout min-h-0 flex-1">
			<div class="kg-main">
				<div class="kg-tools">
					<FilterBar :mode="state.mode" :overlay="state.overlay" :shown="pageCount" :total="rawPageCount"
						@update:mode="(v) => (state.mode = v)" @update:overlay="(v) => (state.overlay = v)" />
					<input class="kg-search" type="text" placeholder="Search nodes…" v-model="state.search" />
					<span v-if="state.focus" class="kg-focus">Focused · <a href="#" @click.prevent="state.focus = null">clear</a></span>
				</div>
				<ExclusionRules class="kg-excl" :page-types="pageTypes" :excluded="state.excluded"
					@update:excluded="onExclude" />
				<Graph3D :data="filtered" :metrics="state.analysis.metrics" :mode="state.mode"
					:dark="dark" @node-click="onNode" />
			</div>
			<div class="kg-side">
				<DetailPanel :node="state.selected" :metrics="state.analysis.metrics"
					:communities="state.analysis.communities" :show-actions="false" @focus="(id) => (state.focus = id)" />
				<AnalysisTabs :analysis="state.analysis" :nodes="baseData.nodes" :actions="state.actions"
					:history="state.history" :can-act="false" :show-priority="false" @pick="pickId" />
			</div>
		</div>

		<div v-if="state.toast" class="kg-toast">{{ state.toast }}</div>
	</div>
</template>

<script setup>
// Tenant Knowledge Graph — the productive tool. Fetch caller-scoped graph → apply
// exclusion → worker analysis (structure + TF-IDF similarity) → 3D graph + the
// four analysis tabs. Productive loop: accept a suggested connection → add_wiki_link
// (durable, out-of-body) → refetch → the edge appears.
import { reactive, computed, watch, onMounted } from "vue"
import { Button } from "frappe-ui"
import {
	Graph3D, FilterBar, DetailPanel, AnalysisTabs, ExclusionRules,
	runAnalysis, computeActions, overlayFilter, egoGraph, searchGraph,
} from "wiki-graph-core"
import { getWikiGraph, getWikiGraphHistory } from "@/api/wiki"

const PAGE_TYPES = ["Customer", "Supplier", "Item", "Process", "Doctype", "Exception", "Integration", "People", "Org"]

const state = reactive({
	data: { nodes: [], edges: [] },
	analysis: { metrics: {}, lists: {}, communities: {} },
	actions: {},
	history: [],
	loaded: false, error: null, selected: null,
	mode: "kind", overlay: "knowledge", search: "", focus: null, toast: "",
	excluded: readExcluded(),
})
const dark = document.documentElement.getAttribute("data-theme") === "dark"

function readExcluded() {
	try { return JSON.parse(localStorage.getItem("wg-excl") || "[]") } catch (_) { return [] }
}
function onExclude(list) {
	state.excluded = list
	try { localStorage.setItem("wg-excl", JSON.stringify(list)) } catch (_) {}
}

function applyExclusion(data, excluded) {
	if (!excluded || !excluded.length) return data
	const ex = new Set(excluded)
	const nodes = (data.nodes || []).filter((n) => n.kind !== "page" || !ex.has(n.page_type))
	const ids = new Set(nodes.map((n) => n.id))
	const edges = (data.edges || []).filter((e) => ids.has(e.source) && ids.has(e.target))
	return { nodes, edges, gaps: data.gaps, co_read: data.co_read }
}

const baseData = computed(() => applyExclusion(state.data, state.excluded))
const rawPageCount = computed(() => (state.data.nodes || []).filter((n) => n.kind === "page").length)
const pageCount = computed(() => baseData.value.nodes.filter((n) => n.kind === "page").length)
const linkCount = computed(() => baseData.value.edges.filter((e) => e.kind === "links-to").length)
const pageTypes = computed(() => {
	const present = new Set((state.data.nodes || []).filter((n) => n.kind === "page").map((n) => n.page_type))
	return PAGE_TYPES.filter((t) => present.has(t))
})
const filtered = computed(() => {
	const g = overlayFilter(baseData.value, state.overlay)
	if (state.focus) return egoGraph(g, state.focus, 2)
	if (state.search) return searchGraph(g, state.search, 1)
	return g
})

let _seq = 0
async function recompute() {
	const token = ++_seq
	const data = baseData.value
	const analysis = await runAnalysis(data)
	if (token !== _seq) return // a newer recompute superseded us
	state.analysis = analysis
	state.actions = computeActions(data, analysis)
}

async function load() {
	state.loaded = false
	state.error = null
	try {
		const d = await getWikiGraph()
		state.data = d || { nodes: [], edges: [] }
		// Measured evolution history (best-effort; empty until the daily job runs
		// or the doctype is migrated in — the Evolution tab reconstructs meanwhile).
		getWikiGraphHistory().then((h) => { state.history = Array.isArray(h) ? h : [] }).catch(() => {})
		await recompute()
	} catch (e) {
		state.error = (e && e.message) || String(e)
	} finally {
		state.loaded = true
	}
}

// Same "Open ERPNext Desk" affordance the other tabs inherit from LayoutHeader.
function openDesk() { window.open("/app", "_blank") }
function onNode(node) { state.selected = node }
function pickId(id) {
	const n = (state.data.nodes || []).find((x) => x.id === id)
	if (n) state.selected = n
}
watch(() => state.excluded, recompute)
onMounted(load)
</script>

<style scoped>
.kg { padding: 4px 2px; }
.kg-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 6px; }
.kg-desk { margin-left: auto; align-self: center; }
.kg-layout { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 16px; }
/* min-width:0 lets the graph column shrink to its track — without it the
   3d-force-graph canvas (an explicit-pixel-width element) forces the column
   wider than the viewport and shoves the side panel off-screen. */
.kg-main { min-width: 0; }
.kg-side { display: flex; flex-direction: column; gap: 14px; overflow-y: auto; }
.kg-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 6px; }
.kg-excl { margin-bottom: 8px; }
.kg-search { font-size: 12px; padding: 4px 10px; border: 1px solid var(--border-color, #d1d8dd); border-radius: 6px; min-width: 180px; }
.kg-focus { font-size: 12px; background: var(--bg-blue, #4c9aff); color: #fff; border-radius: 10px; padding: 1px 10px; }
.kg-focus a { color: #fff; text-decoration: underline; }
.kg-err { color: #d9534f; padding: 16px 0; }
.kg-empty { padding: 24px 4px; font-size: 13px; }
.kg-btn { font-size: 12px; padding: 3px 10px; border: 1px solid var(--border-color, #d1d8dd); border-radius: 6px; background: var(--card-bg, #fff); cursor: pointer; margin-left: 8px; }
.kg-skel { height: 60vh; border-radius: 8px; background: var(--control-bg, #f3f4f6); animation: kg-pulse 1.4s ease-in-out infinite; }
@keyframes kg-pulse { 0%, 100% { opacity: 0.5; } 50% { opacity: 0.9; } }
.kg-toast { position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%); background: #222; color: #fff; padding: 8px 16px; border-radius: 8px; font-size: 13px; z-index: 50; }
/* Only stack (panel below the graph) on genuinely narrow screens. The old
   1100px breakpoint hid the analysis panel off-screen on ordinary
   retina-scaled laptop widths — it read as "the panel is missing". */
@media (max-width: 760px) { .kg-layout { grid-template-columns: 1fr; } }
</style>
