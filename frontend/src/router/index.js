import { createRouter, createWebHistory } from "vue-router"
import { isReadyForChat } from "@/api.js"
import { isOnboardComplete } from "@/onboarding/steps.js"
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
	// Account: plan/billing + AI models editor + connection/usage summaries —
	// System-Manager only; guard redirects others to Chat.
	{
		path: "/account",
		name: "Account",
		component: () => import("@/views/AccountView.vue"),
		beforeEnter: (to, from, next) => { next(window.is_system_manager ? undefined : { name: "Chat" }) },
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
		beforeEnter: (to, from, next) => { next(window.is_system_manager ? undefined : { name: "Chat" }) },
	},
	// Usage dashboard (moved out of the old /ai shell) — System-Manager only;
	// guard redirects others to Chat.
	{
		path: "/monitor",
		name: "Monitor",
		component: () => import("@/views/MonitorView.vue"),
		beforeEnter: (to, from, next) => { next(window.is_system_manager ? undefined : { name: "Chat" }) },
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
// /onboarding link back to Chat. The readiness check hits the backend once
// per page load — `readyPromise` caches the in-flight/resolved call so
// repeated client-side navigations (Chat -> Account -> Chat, etc.) don't
// re-fire it. Fail-open: if the backend call throws, treat the app as ready
// so a flaky check never strands the user unable to reach Chat.
let readyPromise = null
router.beforeEach(async (to) => {
	if (!readyPromise) {
		readyPromise = isReadyForChat().catch(() => ({ ready: true }))
	}
	const ready = isOnboardComplete(await readyPromise)
	// We no longer force not-ready users into the wizard — onboarding is now
	// invited via the chat welcome card (below) + the desk banner. Only bounce a
	// fully-onboarded user away from a stale /onboarding link.
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
