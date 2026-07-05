<template>
	<div class="mt-4 border-t pt-4">
		<div class="flex flex-wrap items-center justify-between gap-2">
			<div class="text-base font-medium text-ink-gray-9">
				Findings — run {{ runLabel }}
			</div>
			<div class="flex items-center gap-2">
				<Button
					v-for="c in STATE_CHIPS"
					:key="c.value"
					:label="c.label"
					:variant="stateFilter === c.value ? 'solid' : 'subtle'"
					@click="stateFilter = c.value"
				/>
			</div>
		</div>

		<div v-if="loading && !rows.length" class="py-6 text-sm text-ink-gray-5">
			Loading findings…
		</div>
		<div v-else-if="!rows.length" class="py-6 text-sm text-ink-gray-5">
			No {{ stateFilter ? stateFilter + " " : "" }}findings for this run.
		</div>

		<ListView
			v-else
			class="mt-3"
			:columns="columns"
			:rows="rows"
			row-key="name"
			:options="{ selectable: false, rowHeight: 40, resizeColumn: false, showTooltip: true }"
		>
			<template #default>
				<ListHeader>
					<ListHeaderItem v-for="column in columns" :key="column.key" :item="column" />
				</ListHeader>
				<ListRows />
			</template>
			<template #cell="{ column, row, item, align }">
				<Badge
					v-if="column.key === 'severity'"
					variant="subtle"
					:theme="SEVERITY_THEME[row.severity] || 'gray'"
					:label="row.severity"
				/>
				<div v-else-if="column.key === 'rule_id'" class="truncate font-mono text-sm">
					{{ row.rule_id || "—" }}
				</div>
				<div v-else-if="column.key === '_ref'" class="truncate text-base">
					<a
						v-if="row.ref_doctype && row.ref_name"
						:href="refUrl(row)"
						target="_blank"
						rel="noopener"
						class="text-ink-gray-8 hover:underline"
						@click.stop
					>
						{{ row.ref_doctype }} {{ row.ref_name }}
					</a>
					<span v-else class="text-ink-gray-4">—</span>
				</div>
				<div v-else-if="column.key === 'amount'" class="flex w-full items-center justify-end">
					<span v-if="row.amount != null && row.amount !== ''" class="truncate text-base">
						{{ fmtAmount(row.amount) }}
					</span>
					<span v-else class="text-base text-ink-gray-4">—</span>
				</div>
				<div v-else-if="column.key === '_state'" class="w-full" @click.stop>
					<FormControl
						type="select"
						:options="STATE_OPTIONS"
						:modelValue="row.state"
						:disabled="busy === row.name"
						@update:modelValue="(v) => moveFinding(row, v)"
					/>
				</div>
				<ListRowItem v-else :column="column" :row="row" :item="item" :align="align" />
			</template>
		</ListView>
	</div>
</template>

<script setup>
// FindingsPanel — the run drill-down under the Runs tab (DESIGN-V3 §7.2):
// state filter chips (all/open/acknowledged/resolved) → findings table with a
// per-row state select → setFindingState (optimistic, toast on error).
import { ref, computed, watch } from "vue"
import {
	Badge,
	Button,
	FormControl,
	ListView,
	ListHeader,
	ListHeaderItem,
	ListRows,
	ListRowItem,
	toast,
} from "frappe-ui"
import { timeAgo } from "@/utils/datetime"
import * as api from "@/api"

const props = defineProps({
	run: { type: Object, required: true }, // {name, started_at, ...} from list_runs
})

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

const SEVERITY_THEME = { blocker: "red", warning: "orange", note: "gray" }
const STATE_CHIPS = [
	{ label: "All", value: "" },
	{ label: "Open", value: "open" },
	{ label: "Acknowledged", value: "acknowledged" },
	{ label: "Resolved", value: "resolved" },
]
const STATE_OPTIONS = [
	{ label: "Open", value: "open" },
	{ label: "Acknowledged", value: "acknowledged" },
	{ label: "Resolved", value: "resolved" },
]

const columns = [
	{ label: "Severity", key: "severity", width: "7rem" },
	{ label: "Rule", key: "rule_id", width: "9rem" },
	{ label: "Finding", key: "title", width: 2 },
	{ label: "Reference", key: "_ref", width: "11rem" },
	{ label: "Amount", key: "amount", width: "7rem", align: "right" },
	{ label: "State", key: "_state", width: "10rem", align: "right" },
]

const rows = ref([])
const loading = ref(false)
const stateFilter = ref("")
const busy = ref("")

const runLabel = computed(() =>
	props.run && props.run.started_at ? timeAgo(props.run.started_at) : props.run.name
)

async function load() {
	if (!props.run || !props.run.name) return
	loading.value = true
	try {
		rows.value =
			(await api.listAgentFindings({
				run: props.run.name,
				state: stateFilter.value || undefined,
				limit: 100,
			})) || []
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		loading.value = false
	}
}

watch(
	() => props.run && props.run.name,
	() => {
		rows.value = []
		load()
	},
	{ immediate: true }
)
watch(stateFilter, load)

async function moveFinding(f, state) {
	if (!state || state === f.state || busy.value) return
	const prev = f.state
	f.state = state // optimistic
	busy.value = f.name
	try {
		await api.setFindingState(f.name, state)
		toast.success(`Finding ${state}`)
	} catch (e) {
		f.state = prev
		toast.error(errMsg(e))
	} finally {
		busy.value = ""
	}
}

function refUrl(row) {
	const dt = String(row.ref_doctype || "").toLowerCase().replace(/ /g, "-")
	return `/app/${dt}/${encodeURIComponent(row.ref_name)}`
}
function fmtAmount(v) {
	const n = Number(v)
	return isNaN(n) ? String(v) : n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}
</script>
