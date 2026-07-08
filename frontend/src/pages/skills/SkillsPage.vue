<template>
	<div class="flex h-full flex-col overflow-hidden">
		<!-- Tab strip renders for System Managers (Skills / Learning / Business /
		     Wiki) and for regular desk users who pass the Business probe (Skills /
		     Business / Wiki). Portal/guest-ish sessions that fail both probes see
		     exactly today's Skills list with no tab chrome (zero regression).
		     The active tab stays "skills" until a probe lands, so SkillsList
		     mounts once and is NOT remounted when the strip later appears —
		     only clicking another tab swaps the body (v-if so exactly one
		     LayoutHeader teleports to #app-header at a time, the Macros-page
		     precedent). -->
		<TabBar
			v-if="isSM || businessAllowed"
			class="shrink-0"
			:tabs="tabs"
			:model-value="activeTab"
			@update:model-value="setTab"
		/>

		<SkillsList v-if="activeTab === 'skills'" class="min-h-0 flex-1" />
		<LearningTab
			v-else-if="activeTab === 'learning'"
			class="min-h-0 flex-1"
			@changed="refreshBadge"
		/>
		<WikiTab v-else-if="activeTab === 'wiki'" class="min-h-0 flex-1" />
		<KnowledgeGraph v-else-if="activeTab === 'graph'" class="min-h-0 flex-1" />
		<BusinessTab v-else class="min-h-0 flex-1" />
	</div>
</template>

<script setup>
// SkillsPage — the routed component for /skills (plan §6.4, owner-mandated):
// wraps the existing Skills list in a hash-synced tab shell (mirrors the
// Agents page). Tab "Skills" renders SkillsList.vue unchanged; tab "Learning"
// (#learning) renders the pattern-learning review board + settings; tab
// "Business" (#business) renders the voice-notes surface; tab "Wiki" (#wiki)
// renders the scope-aware org wiki list. Learning is offered to System
// Managers only — get_learning_status is the SM probe (it throws for everyone
// else). Business and Wiki are offered to any desk user — get_business_status
// is the probe (403s for portal users), so the strip stays hidden for them
// and the page behaves exactly as before.
import { ref, computed, onMounted, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import TabBar from "@/components/list/TabBar.vue"
import SkillsList from "./SkillsList.vue"
import LearningTab from "./LearningTab.vue"
import BusinessTab from "./BusinessTab.vue"
import WikiTab from "./WikiTab.vue"
import KnowledgeGraph from "@/pages/wiki/KnowledgeGraph.vue"
import { renderer3dEnabled } from "wiki-graph-core"
import { getLearningStatus, pendingLearnedCount } from "@/api/learning"
import { getBusinessStatus } from "@/api/voice"

const route = useRoute()
const router = useRouter()

const isSM = ref(false)
const businessAllowed = ref(false)
const learningPending = ref(0)
const activeTab = ref("skills")
// Knowledge Graph tab is behind the per-surface renderer flag (R10, default off);
// flip via localStorage.wg3d = "on" until the 3D renderer soaks in prod.
const graph3dOn = renderer3dEnabled()

const tabs = computed(() => {
	const t = [{ label: "Skills", value: "skills" }]
	if (isSM.value)
		t.push({ label: "Learning", value: "learning", count: learningPending.value || null })
	if (isSM.value || businessAllowed.value) {
		// any desk user passes the Business probe — Wiki rides the same gate
		// (no extra probe; portal/guest sessions never see the strip at all)
		t.push({ label: "Business", value: "business" })
		t.push({ label: "Wiki", value: "wiki" })
		if (graph3dOn) t.push({ label: "Knowledge Graph", value: "graph" })
	}
	return t
})

// hash-synced tabs (Agents precedent; no hash = Skills). "#learning" only
// resolves once we know the viewer is an SM, and "#business"/"#wiki" once a
// probe has confirmed access — an unauthorized deep link falls back to the
// Skills tab.
// "#skills" is intentionally never used (the router keeps that legacy chat
// deep-link mapping /jarvis/#skills → /skills untouched).
function applyHash() {
	const h = (route.hash || "").replace(/^#/, "")
	if (h === "learning" && isSM.value) activeTab.value = "learning"
	else if (h === "business" && (isSM.value || businessAllowed.value))
		activeTab.value = "business"
	else if (h === "wiki" && (isSM.value || businessAllowed.value)) activeTab.value = "wiki"
	else if (h === "graph" && graph3dOn && (isSM.value || businessAllowed.value)) activeTab.value = "graph"
	else activeTab.value = "skills"
}
function setTab(v) {
	if (v === activeTab.value) return
	if (v === "learning" && !isSM.value) return
	if ((v === "business" || v === "wiki") && !(isSM.value || businessAllowed.value)) return
	if (v === "graph" && !(graph3dOn && (isSM.value || businessAllowed.value))) return
	activeTab.value = v
	router.push({ hash: v === "skills" ? "" : `#${v}` })
}
applyHash()
// back/forward restores the tab (guard to this route so other pages' hashes,
// e.g. doc-page tabs, are ignored)
watch(
	() => route.hash,
	() => {
		if (route.name === "SkillsList") applyHash()
	}
)

async function refreshBadge() {
	try {
		learningPending.value = (await pendingLearnedCount()) || 0
	} catch (e) {
		// best-effort badge; a transient failure must not disturb the page
	}
}

onMounted(async () => {
	// both probes in parallel, but flip the refs together only after BOTH have
	// settled — otherwise the strip could show [Skills, Business] and Business
	// would visibly jump to slot 3 when the Learning probe lands later. The
	// strip goes straight from hidden to its final stable order, and applyHash
	// resolves any deep-linked #learning/#business at that same instant.
	const [sm, biz] = await Promise.allSettled([
		getLearningStatus(), // SM-only; throws (403) for everyone else
		getBusinessStatus(), // any desk user; throws for portal/guest
	])
	isSM.value = sm.status === "fulfilled"
	businessAllowed.value = biz.status === "fulfilled"
	applyHash()
	if (isSM.value) refreshBadge()
})
</script>
