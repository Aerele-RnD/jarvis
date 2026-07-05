<template>
	<div class="flex h-full flex-col overflow-hidden">
		<LayoutHeader>
			<template #left-header>
				<Breadcrumbs :items="[{ label: 'Agents', route: { name: 'AgentsList' } }]" />
			</template>
			<template #right-header>
				<Dropdown
					v-if="isSM"
					:options="[{ label: 'Apply catalog changes', icon: 'upload-cloud', onClick: applyCatalog }]"
				>
					<Button icon="more-horizontal" variant="ghost" :tooltip="'Catalog admin'" />
				</Dropdown>
			</template>
		</LayoutHeader>

		<!-- §15.3 — exactly 3 tabs, hash-synced (no hash = Available) -->
		<TabBar class="shrink-0" :tabs="tabBarTabs" :model-value="tab" @update:model-value="setTab" />

		<div class="flex-1 overflow-y-auto">
			<!-- per-tab toolbar: search + category chips filtering WITHIN the tab -->
			<div class="flex items-center gap-2 px-5 pt-4">
				<FormControl
					type="text"
					class="w-60 shrink-0"
					placeholder="Search agents"
					:modelValue="searchInput"
					@update:modelValue="onSearch"
				>
					<template #prefix>
						<FeatherIcon name="search" class="size-4 text-ink-gray-5" />
					</template>
				</FormControl>
				<!-- fade cue on the right edge while more chips hide past it -->
				<div class="relative min-w-0 flex-1">
					<div
						ref="chipStrip"
						class="flex items-center gap-2 overflow-x-auto"
						@scroll.passive="updateChipFade"
					>
						<Button
							label="All"
							:variant="category === '' ? 'solid' : 'subtle'"
							@click="category = ''"
						/>
						<Button
							v-for="c in categories"
							:key="c.slug"
							:label="c.title"
							:variant="category === c.slug ? 'solid' : 'subtle'"
							@click="category = c.slug"
						/>
					</div>
					<div
						v-if="chipFade"
						class="pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-[var(--surface-white)]"
					/>
				</div>
			</div>

			<!-- card grid (unchanged cards, no sections) -->
			<div class="px-5 pb-8 pt-5">
				<div v-if="loading" class="py-10 text-center text-sm text-ink-gray-5">
					Loading the catalog…
				</div>
				<div v-else-if="loadError" class="py-10 text-center text-sm text-ink-red-4">
					{{ loadError }}
				</div>
				<div
					v-else-if="!filtered.length"
					class="flex flex-col items-center gap-1 py-16 text-center"
				>
					<FeatherIcon name="cpu" class="size-7.5 text-ink-gray-5" />
					<span class="mt-2 text-lg font-medium text-ink-gray-8">{{ emptyTitle }}</span>
					<span class="text-p-base text-ink-gray-6">{{ emptyDescription }}</span>
				</div>

				<div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
					<div
						v-for="a in filtered"
						:key="a.agent_slug"
						class="flex cursor-pointer gap-4 rounded-lg border p-4 transition hover:bg-surface-gray-1"
						@click="router.push('/agents/' + a.agent_slug)"
					>
						<!-- letter-avatar logo (listing has no image field) -->
						<div
							class="grid h-12 w-12 shrink-0 place-items-center rounded-lg border bg-surface-gray-2 text-lg font-semibold text-ink-gray-6"
						>
							{{ logoText(a) }}
						</div>
						<div class="min-w-0 flex-1">
							<div class="flex flex-wrap items-center gap-2">
								<span class="truncate text-lg font-semibold text-ink-gray-9">{{ a.title }}</span>
								<Badge variant="subtle" theme="gray" :label="a.nature" />
								<Badge
									v-if="a.status === 'Coming Soon'"
									variant="subtle"
									theme="blue"
									label="Coming Soon"
								/>
								<Badge
									v-else-if="a.status === 'Deprecated'"
									variant="subtle"
									theme="red"
									label="Deprecated"
								/>
							</div>
							<p class="mt-1 line-clamp-2 text-base text-ink-gray-6">{{ a.description }}</p>
							<div class="mt-2 flex items-center gap-2 text-sm">
								<Badge variant="outline" theme="gray" :label="categoryTitle(a.category)" />
								<span v-if="a.installed" class="flex items-center gap-1 text-ink-green-3">
									<FeatherIcon name="check" class="size-3" />
									Installed
								</span>
								<Badge
									v-if="a.update_available"
									variant="subtle"
									theme="orange"
									label="Update"
								/>
							</div>
							<div v-if="!a.allowed" class="mt-1 text-sm text-ink-gray-5">
								Available to: {{ (a.allowed_roles || []).join(", ") || "—" }} — ask your
								administrator.
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<script setup>
// Agents marketplace listing — /agents (DESIGN-V3 §15.3, supersedes §7.1's
// sectioned layout). Exactly 3 hash-synced tabs (mirrors AgentDetail's
// hash-tab pattern; no hash = Available, #installed, #featured):
//   Available — whole catalog incl. Coming Soon; Deprecated hidden unless
//               installed; installed rows keep the ✓ marker.
//   Installed — only the user's installs (tab count badge), any status.
//   Featured  — top Published by install_count (fallback: first 6 Published
//               when all counts are zero — the tab must not be empty).
// Every tab: search (300ms debounce, client-side) + category chips ("All" +
// the tab's distinct categories) filtering WITHIN the tab, then the card
// grid. One list_agents() call (D31, catalog ≈ 7). Card click →
// /agents/:slug (always, incl. Coming Soon). SM right-header ⋯ → "Apply
// catalog changes" (rate-limited server-side).
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from "vue"
import { useRoute, useRouter } from "vue-router"
import { Badge, Breadcrumbs, Button, Dropdown, FeatherIcon, FormControl, toast } from "frappe-ui"
import LayoutHeader from "@/components/LayoutHeader.vue"
import TabBar from "@/components/list/TabBar.vue"
import * as api from "@/api"

const route = useRoute()
const router = useRouter()

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

// Display metadata mirroring jarvis/agents/registry.json domains (round-2
// parity; unknown slugs fall back to a prettified slug).
const DOMAINS = [
	{ slug: "audit", title: "Audit & Ledger Scrutiny" },
	{ slug: "compliance", title: "Statutory Compliance" },
	{ slug: "close", title: "Close & Reporting" },
	{ slug: "ap", title: "Accounts Payable" },
	{ slug: "ar", title: "AR & Collections" },
	{ slug: "bank-recon", title: "Bank & Reconciliation" },
	{ slug: "analytical-review", title: "Analytical Review" },
]

// ── data ──────────────────────────────────────────────────────────────────────
const catalog = ref([])
const loading = ref(true)
const loadError = ref("")

async function load() {
	try {
		catalog.value = (await api.listAgents()) || []
		loadError.value = ""
	} catch (e) {
		loadError.value = "Could not load the agent catalog."
	} finally {
		loading.value = false
	}
}

// SM probe (round-2 parity): getAgentAdminOverview succeeds only for System
// Managers — PermissionError hides the ⋯ apply action, no noise.
const isSM = ref(false)
async function probeAdmin() {
	try {
		await api.getAgentAdminOverview()
		isSM.value = true
	} catch (e) {
		isSM.value = false
	}
}

onMounted(() => {
	load()
	probeAdmin()
	chipResizeObserver = new ResizeObserver(updateChipFade)
	if (chipStrip.value) chipResizeObserver.observe(chipStrip.value)
	updateChipFade()
})

// ── chip-strip overflow cue (right-edge fade over the surface background) ────
const chipStrip = ref(null)
const chipFade = ref(false)
let chipResizeObserver = null
function updateChipFade() {
	const el = chipStrip.value
	// visible only while chips are clipped past the right edge
	chipFade.value = !!el && el.scrollWidth - el.clientWidth - el.scrollLeft > 2
}
onBeforeUnmount(() => chipResizeObserver && chipResizeObserver.disconnect())

// ── hash-synced tabs (AgentDetail pattern; no hash = Available) ──────────────
const tab = ref("available")

const installedCount = computed(() => catalog.value.filter((a) => a.installed).length)
const tabBarTabs = computed(() => [
	{ label: "Available", value: "available" },
	// count badge only once the catalog is in — no misleading "0" flash
	{ label: "Installed", value: "installed", count: loading.value ? null : installedCount.value },
	{ label: "Featured", value: "featured" },
])

function applyHash() {
	const h = (route.hash || "").replace(/^#/, "")
	tab.value = h === "installed" || h === "featured" ? h : "available"
}
function setTab(v) {
	if (tab.value === v) return
	tab.value = v
	router.push({ hash: v === "available" ? "" : "#" + v })
}
applyHash()
// back/forward restores the tab
watch(
	() => route.hash,
	() => {
		if (route.name === "AgentsList") applyHash()
	}
)

// ── search (300ms debounce) + category filter, WITHIN the active tab ─────────
const searchInput = ref("")
const search = ref("")
const category = ref("")
let searchTimer = null
function onSearch(v) {
	searchInput.value = v
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => {
		search.value = String(v || "").trim().toLowerCase()
	}, 300)
}
onBeforeUnmount(() => clearTimeout(searchTimer))

// ── tab row sets (before search/category) ────────────────────────────────────
const tabRows = computed(() => {
	const rows = catalog.value
	if (tab.value === "installed") {
		// the user's installs, ANY status — Deprecated included (§15.3)
		return rows.filter((a) => a.installed)
	}
	if (tab.value === "featured") {
		const published = rows.filter((a) => a.status === "Published")
		const withCounts = published.filter((a) => (a.install_count || 0) > 0)
		if (withCounts.length) {
			return [...withCounts]
				.sort((a, b) => (b.install_count || 0) - (a.install_count || 0))
				.slice(0, 6)
		}
		// all counts zero → first 6 Published; the tab must not be empty
		return published.slice(0, 6)
	}
	// Available: whole catalog incl. Coming Soon; Deprecated only when installed
	return rows.filter((a) => a.status !== "Deprecated" || a.installed)
})

// chips = "All" + the ACTIVE tab's distinct categories
const categories = computed(() => {
	const seen = new Set()
	const out = []
	for (const a of tabRows.value) {
		const slug = a.category || "other"
		if (seen.has(slug)) continue
		seen.add(slug)
		out.push({ slug, title: categoryTitle(slug) })
	}
	return out
})

// a chip selected on one tab may not exist on the next — snap back to All
watch(tab, () => {
	if (category.value && !categories.value.some((c) => c.slug === category.value)) {
		category.value = ""
	}
})

// chips differ per tab/catalog — scrollWidth changes without a resize event
watch(
	() => categories.value.length,
	() => nextTick(updateChipFade)
)

const filtered = computed(() =>
	tabRows.value.filter((a) => {
		if (category.value && (a.category || "other") !== category.value) return false
		if (search.value) {
			const hay = `${a.title} ${a.description || ""} ${a.category || ""} ${a.agent_slug}`.toLowerCase()
			if (!hay.includes(search.value)) return false
		}
		return true
	})
)

const filtersActive = computed(() => !!(search.value || category.value))
const emptyTitle = computed(() => {
	if (tab.value === "installed" && !tabRows.value.length) return "No agents installed yet"
	return "No agents match"
})
const emptyDescription = computed(() => {
	if (tab.value === "installed" && !tabRows.value.length) {
		return "Browse the Available tab and install one to get started."
	}
	if (filtersActive.value) return "Try clearing the search or category filter."
	return "The catalog is empty right now."
})

// ── display helpers ──────────────────────────────────────────────────────────
function categoryTitle(slug) {
	const d = DOMAINS.find((x) => x.slug === slug)
	if (d) return d.title
	return String(slug || "other")
		.split("-")
		.map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
		.join(" ")
}
function logoText(a) {
	return String(a.title || a.agent_slug || "?").slice(0, 2).toUpperCase()
}

// ── SM: apply catalog changes ────────────────────────────────────────────────
async function applyCatalog() {
	try {
		await api.applyAgents()
		toast.success("Applying catalog changes — ~30s, one restart")
	} catch (e) {
		toast.error(errMsg(e))
	}
}
</script>
