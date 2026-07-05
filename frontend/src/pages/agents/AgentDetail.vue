<template>
	<div class="flex h-full flex-col overflow-hidden">
		<LayoutHeader>
			<template #left-header>
				<Breadcrumbs
					:items="[
						{ label: 'Agents', route: { name: 'AgentsList' } },
						{ label: (agent && agent.title) || slug },
					]"
				/>
			</template>
			<template #right-header>
				<template v-if="agent && !installation">
					<Button
						variant="solid"
						label="Install"
						:loading="installing"
						:disabled="!canInstall"
						:tooltip="installTooltip"
						@click="install"
					/>
				</template>
				<template v-else-if="agent">
					<Button
						variant="solid"
						label="Run Now"
						iconLeft="play"
						:loading="running"
						:disabled="runDisabled"
						:tooltip="runTooltip"
						@click="runNow"
					/>
					<Dropdown
						:options="[
							{ label: 'Uninstall', icon: 'trash-2', theme: 'red', onClick: confirmUninstall },
						]"
					>
						<Button icon="more-horizontal" variant="ghost" />
					</Dropdown>
				</template>
			</template>
		</LayoutHeader>

		<!-- not found -->
		<div v-if="error" class="flex flex-1 flex-col items-center justify-center gap-3">
			<div class="flex flex-col items-center gap-1">
				<span class="text-lg font-medium text-ink-gray-8">Agent not found</span>
				<span class="text-center text-p-base text-ink-gray-6">{{ error }}</span>
			</div>
			<Button label="Back to Agents" @click="router.push({ name: 'AgentsList' })" />
		</div>
		<div v-else-if="!agent" class="flex-1" />

		<div v-else class="flex-1 overflow-y-auto">
			<!-- ── hero (marketplace template, D29; de-texted per §15.4) ── -->
			<div class="border-b bg-surface-gray-1 px-6 py-6">
				<div class="flex items-start justify-between gap-5">
					<div class="flex min-w-0 gap-5">
						<div
							class="grid h-16 w-16 shrink-0 place-items-center rounded-lg border bg-surface-gray-2 text-2xl font-semibold text-ink-gray-6"
						>
							{{ logoText }}
						</div>
						<div class="min-w-0">
							<h1 class="truncate text-xl font-semibold text-ink-gray-9">{{ agent.title }}</h1>
							<!-- ONE meta line: publisher · version · nature/status badges -->
							<div class="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-ink-gray-5">
								<span class="truncate">{{ heroMetaText }}</span>
								<span>·</span>
								<Badge variant="subtle" theme="gray" :label="agent.nature" />
								<Badge
									v-if="agent.status === 'Coming Soon'"
									variant="subtle"
									theme="blue"
									label="Coming Soon"
								/>
								<Badge
									v-else-if="agent.status === 'Deprecated'"
									variant="subtle"
									theme="red"
									label="Deprecated"
								/>
							</div>
							<!-- one-line tagline; the LONG description lives ONLY in Overview -->
							<p v-if="tagline" class="mt-1 line-clamp-1 text-base text-ink-gray-6">
								{{ tagline }}
							</p>
							<div class="mt-2 flex flex-wrap gap-2">
								<Badge variant="outline" theme="gray" :label="categoryTitle(agent.category)" />
							</div>
						</div>
					</div>
					<div class="flex shrink-0 flex-col items-end gap-3 self-start">
						<div class="flex items-center gap-1 text-sm text-ink-gray-5">
							<FeatherIcon name="download" class="size-3.5" />
							{{ agent.install_count || 0 }} install{{ agent.install_count === 1 ? "" : "s" }}
						</div>
						<Switch
							v-if="installation"
							label="Enabled"
							:modelValue="!!installation.enabled"
							:disabled="togglingEnabled"
							@update:modelValue="setEnabled"
						/>
					</div>
				</div>
				<div v-if="!agent.allowed" class="mt-3 text-sm text-ink-gray-5">
					Available to: {{ (agent.allowed_roles || []).join(", ") || "—" }} — ask your
					administrator.
				</div>
			</div>

			<TabBar :tabs="tabs" :modelValue="tab" @update:modelValue="setTab" />

			<!-- ── Overview ── -->
			<div v-if="tab === 'overview'" class="flex">
				<div class="max-w-3xl flex-1 px-5 py-6">
					<!-- O1: renderMarkdown from @/markdown (escapes HTML first), NOT marked -->
					<div v-if="descriptionHtml" class="prose prose-sm max-w-none" v-html="descriptionHtml" />
					<div v-else class="text-sm text-ink-gray-5">No description yet.</div>
					<div v-if="needs.length" class="mt-8">
						<div class="text-base font-medium text-ink-gray-9">What it needs</div>
						<div class="mt-2 flex flex-wrap gap-1.5">
							<code
								v-for="t in needs"
								:key="t"
								class="rounded bg-surface-gray-2 px-1.5 py-0.5 font-mono text-xs text-ink-gray-7"
							>
								{{ t }}
							</code>
						</div>
					</div>
				</div>
				<!-- static facts panel (no Resizer, D29) -->
				<div class="w-[280px] shrink-0 space-y-6 border-l px-5 py-6">
					<div>
						<div class="text-sm font-medium text-ink-gray-5">Publisher</div>
						<div class="mt-1 text-base text-ink-gray-8">{{ agent.publisher || "Jarvis" }}</div>
					</div>
					<div>
						<div class="text-sm font-medium text-ink-gray-5">Nature</div>
						<div class="mt-1 text-base text-ink-gray-8">
							{{ agent.nature }} · {{ agent.nature === "Auditor" ? "read-only" : "writes drafts" }}
						</div>
					</div>
					<div>
						<div class="text-sm font-medium text-ink-gray-5">Category</div>
						<div class="mt-1 text-base text-ink-gray-8">{{ categoryTitle(agent.category) }}</div>
					</div>
					<div>
						<div class="text-sm font-medium text-ink-gray-5">Version</div>
						<div class="mt-1 flex flex-wrap items-center gap-2 text-base text-ink-gray-8">
							<span>{{ agent.version && agent.version !== "0.0.0" ? "v" + agent.version : "—" }}</span>
							<Badge v-if="updateAvailable" variant="subtle" theme="orange" label="Update available" />
						</div>
						<div v-if="updateAvailable" class="mt-1 text-sm text-ink-gray-5">
							installed v{{ installation.installed_version }}
						</div>
					</div>
					<div>
						<div class="text-sm font-medium text-ink-gray-5">Validated FY</div>
						<div class="mt-1 text-base text-ink-gray-8">{{ agent.validated_for_fy || "—" }}</div>
					</div>
					<div>
						<div class="text-sm font-medium text-ink-gray-5">Allowed roles</div>
						<div class="mt-1 flex flex-wrap gap-1.5">
							<template v-if="(agent.allowed_roles || []).length">
								<Badge
									v-for="r in agent.allowed_roles"
									:key="r"
									variant="subtle"
									theme="gray"
									:label="r"
								/>
							</template>
							<span v-else class="text-base text-ink-gray-8">Everyone</span>
						</div>
					</div>
					<div>
						<div class="text-sm font-medium text-ink-gray-5">Schedule default</div>
						<div class="mt-1 text-base text-ink-gray-8">{{ defaultScheduleText }}</div>
					</div>
				</div>
			</div>

			<!-- ── Configure (installed; §14 F3 + D28 comments) ── -->
			<div v-else-if="tab === 'configure' && installation" class="max-w-2xl space-y-10 px-5 py-6">
				<section>
					<div class="text-base font-medium text-ink-gray-9">Schedule</div>
					<div class="mt-3 space-y-4">
						<Switch
							label="Run automatically"
							:modelValue="sched.enabled"
							@update:modelValue="(v) => (sched.enabled = v)"
						/>
						<div v-if="sched.enabled" class="grid grid-cols-2 gap-4">
							<FormControl
								type="select"
								label="Frequency"
								:options="FREQUENCY_OPTIONS"
								:modelValue="sched.frequency"
								@update:modelValue="(v) => (sched.frequency = v)"
							/>
							<div>
								<FormLabel label="Time" class="mb-1.5" />
								<TimePicker
									:modelValue="sched.time"
									placeholder="09:00"
									@update:modelValue="(v) => (sched.time = v)"
								/>
							</div>
						</div>
						<div v-if="installation.next_run_at" class="text-sm text-ink-gray-5">
							Next run: {{ fmtDt(installation.next_run_at) }}
						</div>
						<Button label="Save schedule" :loading="savingSchedule" @click="saveSchedule" />
					</div>
				</section>

				<section>
					<div class="text-base font-medium text-ink-gray-9">Configuration</div>
					<ConfigForm class="mt-3" :config="parsedConfig" :saving="savingConfig" @save="saveConfig" />
				</section>

				<section class="border-t pt-6">
					<CommentsSection :docmeta="docmeta" :can-comment="true" />
				</section>
			</div>

			<!-- ── Runs (installed) ── -->
			<AgentRunsTab
				v-else-if="tab === 'runs' && installation"
				ref="runsTab"
				:agent-name="agent.name"
			/>

			<!-- ── Admin (SM only; server enforces every call) ── -->
			<div v-else-if="tab === 'admin' && isSM" class="max-w-2xl space-y-10 px-5 py-6">
				<section>
					<div class="text-base font-medium text-ink-gray-9">Listing status</div>
					<div class="mt-3 w-56">
						<FormControl
							type="select"
							:options="LISTING_STATUSES"
							:modelValue="statusDraft"
							:disabled="statusBusy"
							@update:modelValue="onStatusSelect"
						/>
					</div>
					<div class="mt-2 text-sm text-ink-gray-5">
						Published agents are installable; Deprecated hides the listing for
						non-installers.
					</div>
				</section>

				<section>
					<div class="text-base font-medium text-ink-gray-9">Allowed roles</div>
					<div class="mt-2 text-sm text-ink-gray-5">
						Role gating is enforced server-side on every path. An empty list means everyone.
					</div>
					<div class="mt-3 flex flex-wrap gap-1.5">
						<div
							v-for="r in roleDraft"
							:key="r"
							class="flex h-6 items-center gap-1 rounded bg-surface-gray-2 px-2 text-sm text-ink-gray-8"
						>
							<span class="truncate">{{ r }}</span>
							<Button variant="ghost" icon="x" class="!h-4 !w-4" @click="removeRole(r)" />
						</div>
						<span v-if="!roleDraft.length" class="text-sm text-ink-gray-4">
							Everyone — no restriction
						</span>
					</div>
					<div class="mt-3 w-72">
						<Autocomplete
							:options="roleOptions"
							:modelValue="null"
							placeholder="Add a role…"
							@update:modelValue="(opt) => opt && addRole(opt.value)"
						/>
					</div>
					<div v-if="rolesDirty" class="mt-3 flex items-center gap-2">
						<Button label="Save roles" :loading="savingRoles" @click="saveRoles" />
						<Button label="Reset" variant="ghost" @click="resetRoles" />
						<span v-if="!roleDraft.length" class="text-sm text-ink-gray-5">
							Saving with none selected clears the restriction.
						</span>
					</div>
				</section>

				<section>
					<div class="text-base font-medium text-ink-gray-9">
						Installs ({{ installRows.length }})
					</div>
					<div v-if="adminLoading && !adminData" class="mt-3 text-sm text-ink-gray-5">
						Loading installs…
					</div>
					<div v-else-if="!installRows.length" class="mt-3 text-sm text-ink-gray-5">
						No installs yet.
					</div>
					<ListView
						v-else
						class="mt-3"
						:columns="INSTALL_COLUMNS"
						:rows="installRows"
						row-key="installation"
						:options="{ selectable: false, rowHeight: 40, resizeColumn: false, showTooltip: true }"
					>
						<template #default>
							<ListHeader>
								<ListHeaderItem
									v-for="column in INSTALL_COLUMNS"
									:key="column.key"
									:item="column"
								/>
							</ListHeader>
							<ListRows />
						</template>
						<template #cell="{ column, row, item, align }">
							<Badge
								v-if="column.key === 'enabled'"
								variant="subtle"
								:theme="row.enabled ? 'green' : 'gray'"
								:label="row.enabled ? 'Enabled' : 'Disabled'"
							/>
							<div v-else-if="column.key === 'last_run_at'" class="truncate text-base">
								{{ row.last_run_at ? timeAgo(row.last_run_at) : "—" }}
							</div>
							<div v-else-if="column.key === 'sync_status'" class="truncate text-base">
								{{ row.sync_status || "—" }}
							</div>
							<ListRowItem v-else :column="column" :row="row" :item="item" :align="align" />
						</template>
					</ListView>
				</section>
			</div>
		</div>
	</div>
</template>

<script setup>
// Agent detail — /agents/:slug (DESIGN-V3 §7.2, D29/D30 + §14 F3/O1 + §15.4).
// Marketplace template: de-texted hero (logo · name · one meta line ·
// one-line tagline · category chips; install count + Enabled switch right) →
// hash-synced tabs. Overview (markdown description + static facts panel) ·
// Configure (schedule / ConfigForm / CommentsSection on the installation, D28)
// · Runs (AgentRunsTab + findings drill-down) · Admin (SM-only: listing
// status, roles editor, installs overview for this agent).
import { ref, computed, watch, nextTick } from "vue"
import { useRoute, useRouter } from "vue-router"
import {
	Autocomplete,
	Badge,
	Breadcrumbs,
	Button,
	Dropdown,
	FeatherIcon,
	FormControl,
	FormLabel,
	ListView,
	ListHeader,
	ListHeaderItem,
	ListRows,
	ListRowItem,
	Switch,
	TimePicker,
	confirmDialog,
	toast,
} from "frappe-ui"
import LayoutHeader from "@/components/LayoutHeader.vue"
import TabBar from "@/components/list/TabBar.vue"
import CommentsSection from "@/components/doc/CommentsSection.vue"
import AgentRunsTab from "@/pages/agents/AgentRunsTab.vue"
import ConfigForm from "@/pages/agents/ConfigForm.vue"
import { useDocmeta } from "@/composables/useDocmeta"
import { timeAgo, exactDate as fmtDt } from "@/utils/datetime"
import * as api from "@/api"
import * as apiAgents from "@/api/agents"
import { renderMarkdown } from "@/markdown"

const props = defineProps({
	slug: { type: String, required: true },
})

const route = useRoute()
const router = useRouter()

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

// display metadata (mirrors AgentsList / registry.json domains)
const DOMAINS = [
	{ slug: "audit", title: "Audit & Ledger Scrutiny" },
	{ slug: "compliance", title: "Statutory Compliance" },
	{ slug: "close", title: "Close & Reporting" },
	{ slug: "ap", title: "Accounts Payable" },
	{ slug: "ar", title: "AR & Collections" },
	{ slug: "bank-recon", title: "Bank & Reconciliation" },
	{ slug: "analytical-review", title: "Analytical Review" },
]
const FREQUENCY_OPTIONS = [
	{ label: "Daily", value: "daily" },
	{ label: "Weekly", value: "weekly" },
	{ label: "Monthly", value: "monthly" },
]
const LISTING_STATUSES = ["Draft", "Published", "Coming Soon", "Deprecated"]
const INSTALL_COLUMNS = [
	{ label: "Owner", key: "owner", width: 2 },
	{ label: "Enabled", key: "enabled", width: "7rem" },
	{ label: "Last run", key: "last_run_at", width: "8rem" },
	{ label: "Sync", key: "sync_status", width: "7rem" },
]

// ── data ──────────────────────────────────────────────────────────────────────
const agent = ref(null) // get_agent payload (§8.3)
const error = ref("")

async function load() {
	try {
		agent.value = (await apiAgents.getAgent(props.slug)) || null
		error.value = ""
	} catch (e) {
		error.value = errMsg(e)
	}
}
load().then(applyHash)
watch(
	() => props.slug,
	() => {
		agent.value = null
		error.value = ""
		adminData.value = null
		load().then(applyHash)
	}
)

const installation = computed(() => (agent.value && agent.value.installation) || null)
// §8.3: all_roles is present only in the SM payload — the Admin-tab signal
const isSM = computed(() => Array.isArray(agent.value && agent.value.all_roles))
const updateAvailable = computed(
	() =>
		!!(
			installation.value &&
			installation.value.installed_version &&
			agent.value.version &&
			installation.value.installed_version !== agent.value.version
		)
)

// ── hash-synced tabs (useActiveTabManager pattern) ───────────────────────────
const tab = ref("overview")
const runsTab = ref(null)

const tabs = computed(() => {
	const out = [{ label: "Overview", value: "overview" }]
	if (installation.value) {
		out.push({ label: "Configure", value: "configure" })
		out.push({ label: "Runs", value: "runs" })
	}
	if (isSM.value) out.push({ label: "Admin", value: "admin" })
	return out
})

function applyHash() {
	const h = (route.hash || "").replace(/^#/, "")
	tab.value = tabs.value.some((t) => t.value === h) ? h : "overview"
}
function setTab(v) {
	if (tab.value === v && route.hash === "#" + v) return
	tab.value = v
	router.push({ hash: "#" + v })
}
// back/forward restores the tab
watch(
	() => route.hash,
	() => {
		if (route.name === "AgentDetail") applyHash()
	}
)
// tab set no longer valid (e.g. after uninstall) → fall back to overview
watch(tabs, (list) => {
	if (!list.some((t) => t.value === tab.value)) tab.value = "overview"
})

// ── header actions ────────────────────────────────────────────────────────────
const installing = ref(false)
const canInstall = computed(
	() => !!(agent.value && agent.value.allowed && agent.value.status === "Published")
)
const installTooltip = computed(() => {
	if (!agent.value || canInstall.value) return ""
	if (!agent.value.allowed)
		return "Restricted to: " + ((agent.value.allowed_roles || []).join(", ") || "—")
	return agent.value.status === "Coming Soon" ? "Coming soon" : "Not available to install"
})

async function install() {
	if (installing.value || !canInstall.value) return
	installing.value = true
	const p = api.installAgent(props.slug)
	toast.promise(p, {
		loading: "Installing…",
		success: () => `${agent.value.title} installed`,
		error: (e) => errMsg(e),
	})
	try {
		await p
	} catch (e) {
		installing.value = false
		return
	}
	await load()
	installing.value = false
	setTab("configure")
}

const running = ref(false)
const runDisabled = computed(
	() =>
		!installation.value ||
		!installation.value.enabled ||
		(agent.value && agent.value.nature !== "Auditor") ||
		!(agent.value && agent.value.allowed)
)
const runTooltip = computed(() => {
	if (!agent.value || !installation.value) return ""
	if (agent.value.nature !== "Auditor")
		return "Operators draft through the Approval Board — no on-demand runs"
	if (!installation.value.enabled) return "Enable the agent first"
	if (!agent.value.allowed) return "Your roles do not permit this agent"
	return "Run this audit now"
})

async function runNow() {
	if (running.value || runDisabled.value) return
	running.value = true
	try {
		await api.runAgentNow(installation.value.name)
		toast.success("Audit started")
		setTab("runs")
		await nextTick()
		if (runsTab.value) runsTab.value.reload()
		load() // refresh last_run_at etc. in the background
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		running.value = false
	}
}

function confirmUninstall() {
	if (!installation.value) return
	const name = installation.value.name
	confirmDialog({
		title: "Uninstall agent?",
		message: `Remove “${agent.value.title}”? It leaves your assistant on the next catalog apply. Runs and findings are kept.`,
		onConfirm: async ({ hideDialog }) => {
			try {
				await api.uninstallAgent(name)
				hideDialog()
				toast.success("Uninstalled")
				await load()
				setTab("overview")
			} catch (e) {
				toast.error(errMsg(e))
			}
		},
	})
}

const togglingEnabled = ref(false)
async function setEnabled(v) {
	if (!installation.value || togglingEnabled.value) return
	togglingEnabled.value = true
	try {
		await api.setAgentEnabled(installation.value.name, v ? 1 : 0)
		await load()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		togglingEnabled.value = false
	}
}

// ── hero + overview helpers ───────────────────────────────────────────────────
const logoText = computed(() =>
	String((agent.value && agent.value.title) || props.slug || "?").slice(0, 2).toUpperCase()
)
// §15.4 — ONE meta line: "by {publisher} · v{version}" (badges follow inline)
const heroMetaText = computed(() => {
	const parts = ["by " + ((agent.value && agent.value.publisher) || "Jarvis")]
	if (agent.value && agent.value.version && agent.value.version !== "0.0.0") {
		parts.push("v" + agent.value.version)
	}
	return parts.join(" · ")
})
// §15.4 — one-line tagline: first non-empty description line, heading markers
// stripped; the full markdown renders only in the Overview tab
const tagline = computed(() => {
	const d = (agent.value && agent.value.description) || ""
	const line = d.split("\n").find((l) => l.trim()) || ""
	return line.replace(/^#{1,6}\s+/, "").trim()
})
// O1 — renderMarkdown (jv-md-* classes are global via the main chunk)
const descriptionHtml = computed(() =>
	agent.value && agent.value.description ? renderMarkdown(agent.value.description) : ""
)
const needs = computed(() => {
	if (!agent.value) return []
	const out = []
	for (const key of ["tools_required", "min_apps"]) {
		let v = agent.value[key]
		if (typeof v === "string" && v.trim()) {
			try {
				v = JSON.parse(v)
			} catch (e) {
				v = null
			}
		}
		if (Array.isArray(v)) out.push(...v.map(String))
	}
	return out
})
const defaultScheduleText = computed(() => {
	let s = {}
	try {
		s = JSON.parse((agent.value && agent.value.default_schedule) || "{}") || {}
	} catch (e) {
		s = {}
	}
	const freq = String(s.schedule_frequency || "").toLowerCase()
	if (!freq) return "None — runs on demand."
	return s.schedule_enabled ? `On by default · ${freq}` : `Off by default · suggested ${freq}`
})
function categoryTitle(slug) {
	const d = DOMAINS.find((x) => x.slug === slug)
	if (d) return d.title
	return String(slug || "other")
		.split("-")
		.map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
		.join(" ")
}

// ── Configure: schedule ───────────────────────────────────────────────────────
const sched = ref({ enabled: false, frequency: "daily", time: "09:00" })
const savingSchedule = ref(false)
// seed once per installation (a background reload must not clobber edits)
watch(
	() => installation.value && installation.value.name,
	(name) => {
		if (!name) return
		const inst = installation.value
		sched.value = {
			enabled: !!inst.schedule_enabled,
			frequency: inst.schedule_frequency || "daily",
			time: timeHHMM(inst.schedule_time) || "09:00",
		}
	},
	{ immediate: true }
)

async function saveSchedule() {
	if (!installation.value || savingSchedule.value) return
	savingSchedule.value = true
	try {
		await api.setAgentSchedule(installation.value.name, {
			schedule_enabled: sched.value.enabled ? 1 : 0,
			schedule_frequency: sched.value.frequency,
			schedule_time: sched.value.time || "",
		})
		toast.success("Schedule saved")
		await load()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		savingSchedule.value = false
	}
}

// ── Configure: config JSON → ConfigForm (§14 F3) ─────────────────────────────
// keyed off the JSON *string* so unrelated reloads don't reseed the form
const parsedConfig = ref({})
watch(
	() => (installation.value && installation.value.config) || "{}",
	(raw) => {
		try {
			parsedConfig.value = JSON.parse(raw) || {}
		} catch (e) {
			parsedConfig.value = {}
		}
	},
	{ immediate: true }
)

const savingConfig = ref(false)
async function saveConfig(merged) {
	if (!installation.value || savingConfig.value) return
	savingConfig.value = true
	try {
		await api.setAgentConfig(installation.value.name, merged)
		toast.success("Configuration saved")
		await load()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		savingConfig.value = false
	}
}

// ── Configure: comments on the installation (D28, B3 contract) ───────────────
const instName = computed(() => (installation.value && installation.value.name) || null)
const docmeta = useDocmeta("Jarvis Agent Installation", instName)

// ── Admin (SM) ────────────────────────────────────────────────────────────────
const adminData = ref(null) // {roles, listings} from get_agent_admin_overview
const adminLoading = ref(false)

async function loadAdmin() {
	if (adminLoading.value) return
	adminLoading.value = true
	try {
		adminData.value = (await api.getAgentAdminOverview()) || null
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		adminLoading.value = false
	}
}
watch(
	tab,
	(v) => {
		if (v === "admin" && isSM.value && !adminData.value) loadAdmin()
	},
	{ immediate: true }
)

const adminListing = computed(() => {
	const listings = (adminData.value && adminData.value.listings) || []
	return listings.find((l) => l.agent_slug === props.slug) || null
})
const installRows = computed(() => (adminListing.value && adminListing.value.installs) || [])

// status select (draft snaps back unless confirmed/saved)
const statusDraft = ref("")
const statusBusy = ref(false)
watch(
	() => agent.value && agent.value.status,
	(v) => {
		statusDraft.value = v || ""
	},
	{ immediate: true }
)

function onStatusSelect(v) {
	if (!agent.value || !v || v === agent.value.status) return
	if (v === "Deprecated") {
		statusDraft.value = agent.value.status // apply only on confirm
		confirmDialog({
			title: "Deprecate this agent?",
			message:
				"New installs stop and the listing is hidden from non-installers. Existing installs keep running with a Deprecated badge.",
			onConfirm: async ({ hideDialog }) => {
				try {
					await doSetStatus("Deprecated")
					hideDialog()
				} catch (e) {
					toast.error(errMsg(e))
				}
			},
		})
	} else {
		statusDraft.value = v
		doSetStatus(v).catch((e) => {
			statusDraft.value = agent.value.status
			toast.error(errMsg(e))
		})
	}
}

async function doSetStatus(status) {
	statusBusy.value = true
	try {
		const r = await api.setListingStatus(props.slug, status)
		agent.value.status = (r && r.status) || status
		statusDraft.value = agent.value.status
		toast.success(`${agent.value.title} → ${agent.value.status}`)
	} finally {
		statusBusy.value = false
	}
}

// roles editor (Autocomplete over all_roles → chips → Save)
const roleDraft = ref([])
const savingRoles = ref(false)
watch(
	() => agent.value && agent.value.allowed_roles,
	(v) => {
		roleDraft.value = [...(v || [])]
	},
	{ immediate: true }
)
const roleOptions = computed(() => {
	const all = (agent.value && agent.value.all_roles) || []
	const taken = new Set(roleDraft.value)
	return all.filter((r) => !taken.has(r)).map((r) => ({ label: r, value: r }))
})
const rolesDirty = computed(() => {
	const a = [...roleDraft.value].sort().join("|")
	const b = [...((agent.value && agent.value.allowed_roles) || [])].sort().join("|")
	return a !== b
})
function addRole(r) {
	if (!roleDraft.value.includes(r)) roleDraft.value = [...roleDraft.value, r]
}
function removeRole(r) {
	roleDraft.value = roleDraft.value.filter((x) => x !== r)
}
function resetRoles() {
	roleDraft.value = [...((agent.value && agent.value.allowed_roles) || [])]
}
async function saveRoles() {
	if (savingRoles.value) return
	savingRoles.value = true
	try {
		const r = await api.setAgentRoles(props.slug, roleDraft.value)
		agent.value.allowed_roles = (r && r.allowed_roles) || []
		roleDraft.value = [...agent.value.allowed_roles]
		toast.success(
			agent.value.allowed_roles.length
				? "Roles saved"
				: "Restriction cleared — available to everyone"
		)
		load() // refresh allowed/lock state
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		savingRoles.value = false
	}
}

// ── formatting helpers ────────────────────────────────────────────────────────
// "9:00:00" (python str(timedelta)) → "09:00" for the TimePicker
function timeHHMM(s) {
	const m = /^(\d{1,2}):(\d{2})/.exec(String(s || ""))
	return m ? `${m[1].padStart(2, "0")}:${m[2]}` : ""
}
</script>
