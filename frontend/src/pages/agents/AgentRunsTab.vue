<template>
	<div class="px-5 py-6">
		<div v-if="loading && !rows.length" class="py-6 text-sm text-ink-gray-5">Loading runs…</div>
		<div v-else-if="!rows.length" class="flex flex-col items-center gap-1 py-16 text-center">
			<FeatherIcon name="activity" class="size-7.5 text-ink-gray-5" />
			<span class="mt-2 text-lg font-medium text-ink-gray-8">No runs yet</span>
			<span class="text-p-base text-ink-gray-6">
				Use Run Now or a schedule — every run lands here with its findings.
			</span>
		</div>

		<ListView
			v-else
			:columns="columns"
			:rows="rows"
			row-key="name"
			:options="{
				selectable: false,
				rowHeight: 40,
				resizeColumn: false,
				showTooltip: true,
				onRowClick: (row) => (selectedRun = row),
			}"
		>
			<template #default>
				<ListHeader>
					<ListHeaderItem v-for="column in columns" :key="column.key" :item="column" />
				</ListHeader>
				<ListRows />
			</template>
			<template #cell="{ column, row, item, align }">
				<div v-if="column.key === 'started_at'" class="truncate text-base">
					<Tooltip :text="exactDate(row.started_at)">
						<span>{{ timeAgo(row.started_at) || "—" }}</span>
					</Tooltip>
				</div>
				<Badge
					v-else-if="column.key === 'status'"
					variant="subtle"
					:theme="STATUS_THEME[row.status] || 'gray'"
					:label="row.status"
				/>
				<div v-else-if="column.key === '_findings'" class="truncate text-base">
					{{ row.findings_count || 0 }} finding{{ (row.findings_count || 0) === 1 ? "" : "s" }}
					<span v-if="row.blocker_count" class="text-ink-red-4">
						· {{ row.blocker_count }} blocker{{ row.blocker_count === 1 ? "" : "s" }}
					</span>
				</div>
				<div v-else-if="column.key === '_chat'" class="flex w-full items-center justify-end">
					<Button
						v-if="row.conversation"
						variant="ghost"
						icon="message-circle"
						:tooltip="'Open conversation'"
						@click.stop="router.push('/c/' + row.conversation)"
					/>
				</div>
				<ListRowItem v-else :column="column" :row="row" :item="item" :align="align" />
			</template>
		</ListView>

		<!-- findings drill-down for the clicked run -->
		<FindingsPanel v-if="selectedRun" :run="selectedRun" />
	</div>
</template>

<script setup>
// AgentRunsTab — the Runs tab of /agents/:slug (DESIGN-V3 §7.2): this owner's
// run history for ONE agent (list_runs(agent)), row click → FindingsPanel
// drill-down below. The parent jumps here after Run Now and calls reload()
// through the exposed handle.
import { ref, watch } from "vue"
import { useRouter } from "vue-router"
import {
	Badge,
	Button,
	FeatherIcon,
	ListView,
	ListHeader,
	ListHeaderItem,
	ListRows,
	ListRowItem,
	Tooltip,
	toast,
} from "frappe-ui"
import FindingsPanel from "@/pages/agents/FindingsPanel.vue"
import { timeAgo, exactDate } from "@/utils/datetime"
import * as api from "@/api"

const props = defineProps({
	agentName: { type: String, required: true }, // listing docname (list_runs filter)
})

const router = useRouter()

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

const STATUS_THEME = { running: "blue", completed: "green", partial: "orange", failed: "red" }

const columns = [
	{ label: "Started", key: "started_at", width: "10rem" },
	{ label: "Trigger", key: "trigger", width: "6rem" },
	{ label: "Status", key: "status", width: "7rem" },
	{ label: "Findings", key: "_findings", width: "12rem" },
	{ label: "Note", key: "coverage_note", width: 2 },
	{ label: "", key: "_chat", width: "4rem", align: "right" },
]

const rows = ref([])
const loading = ref(false)
const selectedRun = ref(null)

async function reload() {
	loading.value = true
	try {
		rows.value = (await api.listAgentRuns(props.agentName, 50)) || []
		// keep the drill-down pinned to the same run across refreshes
		if (selectedRun.value) {
			selectedRun.value = rows.value.find((r) => r.name === selectedRun.value.name) || null
		}
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		loading.value = false
	}
}

watch(
	() => props.agentName,
	() => {
		rows.value = []
		selectedRun.value = null
		reload()
	},
	{ immediate: true }
)

defineExpose({ reload })
</script>
