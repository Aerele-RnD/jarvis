<template>
	<div class="flex h-full flex-col overflow-hidden">
		<!-- Tab strip only for System Managers: the Learning board + settings are
		     SM-gated + managed-only. Non-SM users see exactly today's Skills list
		     with no tab chrome (zero regression). The active tab stays "skills"
		     while isSM is false, so SkillsList mounts once and is NOT remounted
		     when the strip later appears — only clicking Learning swaps the body
		     (v-if so exactly one LayoutHeader teleports to #app-header at a time,
		     the Macros-page precedent). -->
		<TabBar
			v-if="isSM"
			class="shrink-0"
			:tabs="tabs"
			:model-value="activeTab"
			@update:model-value="setTab"
		/>

		<SkillsList v-if="activeTab === 'skills'" class="min-h-0 flex-1" />
		<LearningTab v-else class="min-h-0 flex-1" @changed="refreshBadge" />
	</div>
</template>

<script setup>
// SkillsPage — the routed component for /skills (plan §6.4, owner-mandated):
// wraps the existing Skills list in a two-tab, hash-synced shell (mirrors the
// Agents page). Tab "Skills" renders SkillsList.vue unchanged; tab "Learning"
// (#learning) renders the pattern-learning review board + settings. The
// Learning tab is offered to System Managers only — get_learning_status is the
// SM probe (it throws for everyone else), so the strip stays hidden for normal
// users and the page behaves exactly as before for them.
import { ref, computed, onMounted, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import TabBar from "@/components/list/TabBar.vue"
import SkillsList from "./SkillsList.vue"
import LearningTab from "./LearningTab.vue"
import { getLearningStatus, pendingLearnedCount } from "@/api/learning"

const route = useRoute()
const router = useRouter()

const isSM = ref(false)
const learningPending = ref(0)
const activeTab = ref("skills")

const tabs = computed(() => [
	{ label: "Skills", value: "skills" },
	{ label: "Learning", value: "learning", count: learningPending.value || null },
])

// hash-synced tabs (Agents precedent; no hash = Skills). "#learning" only
// resolves once we know the viewer is an SM — a non-SM deep link falls back to
// the Skills tab. "#skills" is intentionally never used (the router keeps that
// legacy chat deep-link mapping /jarvis/#skills → /skills untouched).
function applyHash() {
	const h = (route.hash || "").replace(/^#/, "")
	activeTab.value = h === "learning" && isSM.value ? "learning" : "skills"
}
function setTab(v) {
	if (v === activeTab.value) return
	if (v === "learning" && !isSM.value) return
	activeTab.value = v
	router.push({ hash: v === "learning" ? "#learning" : "" })
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
	try {
		await getLearningStatus() // SM-only; throws (403) for everyone else
		isSM.value = true
		applyHash() // reflect a deep-linked #learning now that SM is confirmed
		refreshBadge()
	} catch (e) {
		isSM.value = false
	}
})
</script>
