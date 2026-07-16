import { createRouter, createWebHistory } from "vue-router"
import { isWorkspaceReady } from "@/onboarding/readiness.js"
// STATIC import: the main chunk = shell + store + ChatView (chat is the app
// home, D33); every other page is a route-level dynamic import.
import ChatView from "@/views/ChatView.vue"

const routes = [
	{ path: "/", name: "Chat", component: ChatView, meta: { chat: true } },
	{ path: "/c/:id", name: "Conversation", component: ChatView, meta: { chat: true } },
	// /skills renders the two-tab shell (Skills | Learning). The name stays
	// "SkillsList" so every router.push({name:'SkillsList'}), the sidebar link,
	// the command palette and SkillsList's own breadcrumb keep resolving here;
	// the #skills legacy hash deep-link (HASH_ROUTES below) is unaffected.
	{ path: "/skills", name: "SkillsList", component: () => import("@/pages/skills/SkillsPage.vue") },
	{
		path: "/skills/new",
		name: "SkillNew",
		component: () => import("@/pages/skills/SkillDetail.vue"),
		props: { isNew: true },
	},
	{
		path: "/skills/:id",
		name: "SkillDetail",
		component: () => import("@/pages/skills/SkillDetail.vue"),
		props: true,
	},
	// First-run wizard (managed signup or self-hosted connect) — System-Manager
	// only; guard redirects others to Chat. Reached via the chat welcome card
	// or the desk banner, not a forced redirect (see beforeEach below).
	{
		path: "/onboarding",
		name: "Onboarding",
		component: () => import("@/views/OnboardingView.vue"),
		// Chrome-less: a first-run customer hasn't onboarded yet, so the full app
		// sidebar/header (Chat/Skills/Macros/…) is noise — AppShell hides them.
		meta: { chromeless: true },
		// PART 4 REVISED TASK 49(c): a Jarvis Admin (not necessarily SM) may onboard.
		beforeEnter: (to, from, next) => { next((window.is_system_manager || window.is_jarvis_admin) ? undefined : { name: "Chat" }) },
	},
	{ path: "/macros", name: "MacrosList", component: () => import("@/pages/macros/MacrosList.vue") },
	{
		path: "/macros/runs",
		name: "MacroRuns",
		component: () => import("@/pages/macros/MacrosList.vue"),
		props: { tab: "runs" },
	},
	{
		path: "/macros/new",
		name: "MacroNew",
		component: () => import("@/pages/macros/MacroDetail.vue"),
		props: { isNew: true },
	},
	{
		path: "/macros/:id",
		name: "MacroDetail",
		component: () => import("@/pages/macros/MacroDetail.vue"),
		props: true,
	},
	// Triggers: /triggers is the hash-tabbed shell (Triggers | #activity);
	// /triggers/new and /triggers/:id share the detail page (isNew prop, the
	// Macros shape). "new" is registered BEFORE :id so it can't be shadowed.
	{
		path: "/triggers",
		name: "TriggersPage",
		component: () => import("@/pages/triggers/TriggersPage.vue"),
	},
	{
		path: "/triggers/new",
		name: "TriggerNew",
		component: () => import("@/pages/triggers/TriggerDetail.vue"),
		props: { isNew: true },
	},
	{
		path: "/triggers/:id",
		name: "TriggerDetail",
		component: () => import("@/pages/triggers/TriggerDetail.vue"),
		props: true,
	},
	{ path: "/files", name: "FilesList", component: () => import("@/pages/files/FilesList.vue") },
	// §15.2: both approval routes render the two-pane board (the :id row is
	// selected in place); names kept so nav highlighting + router.push targets
	// keep working. The board reads route.params itself — no props.
	{
		path: "/approvals",
		name: "ApprovalsList",
		component: () => import("@/pages/approvals/ApprovalsBoard.vue"),
	},
	{
		path: "/approvals/:id",
		name: "ApprovalDetail",
		component: () => import("@/pages/approvals/ApprovalsBoard.vue"),
	},
	{ path: "/agents", name: "AgentsList", component: () => import("@/pages/agents/AgentsList.vue") },
	// Legacy round-2 tab routes — static, registered BEFORE :slug (§9). Point at
	// the current hash-tabs (mine→Installed, activity→Activity); admin is now a
	// per-agent detail tab, so it falls back to the catalog.
	{ path: "/agents/mine", redirect: "/agents#installed" },
	{ path: "/agents/activity", redirect: "/agents#activity" },
	{ path: "/agents/admin", redirect: "/agents" },
	{
		path: "/agents/:slug",
		name: "AgentDetail",
		component: () => import("@/pages/agents/AgentDetail.vue"),
		props: true,
	},
]

// Served under /jarvis (website_route_rules catch-all → www/jarvis page).
const router = createRouter({
	history: createWebHistory("/jarvis"),
	routes,
})

// First-run guard: bounce a fully-onboarded user away from a stale
// /onboarding link back to Chat. Readiness is resolved once per page load via
// the shared, memoized helper (see @/onboarding/readiness.js) — the AppShell
// onboarding gate reads the SAME promise, so the two stay consistent and only
// one backend round-trip fires. Fail-open lives in the helper.
//
// The reverse direction (forcing a NOT-ready user into the wizard) is
// deliberately NOT a redirect here: the old D11 forced redirect looped between
// the desk and SPA onboarding pages and bricked fresh sites. Instead, AppShell
// blocks the app with a rendered, no-sidebar poster when not ready — a render,
// not a navigation, so it cannot loop.
router.beforeEach(async (to) => {
	const ready = await isWorkspaceReady()
	if (ready && to.name === "Onboarding") {
		return { name: "Chat" }
	}
	return true
})

// Legacy hash deep-links (moved out of ChatView, §9): /jarvis/#skills etc.
// map to real routes. Applies only on chat routes so doc-page tab hashes
// (#overview on /agents/:slug) are unaffected.
const HASH_ROUTES = {
	"#skills": "/skills",
	"#macros": "/macros",
	"#filebox": "/files",
	"#approvals": "/approvals",
	"#agents": "/agents",
}
function applyLegacyHash() {
	const target = HASH_ROUTES[window.location.hash]
	if (!target) return
	const current = router.currentRoute.value
	if (current.name && current.meta.chat !== true) return
	router.replace(target)
}
router.isReady().then(applyLegacyHash)
window.addEventListener("hashchange", applyLegacyHash)

export default router
