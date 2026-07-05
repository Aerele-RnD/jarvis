import { createRouter, createWebHistory } from "vue-router"
import { isReadyForChat } from "@/api.js"
import { isOnboardComplete } from "@/onboarding/steps.js"

const routes = [
	{
		path: "/",
		name: "Chat",
		component: () => import("@/views/ChatView.vue"),
	},
	// Deep link to a specific conversation; ChatView reads the param.
	{
		path: "/c/:id",
		name: "Conversation",
		component: () => import("@/views/ChatView.vue"),
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
	// Agents Marketplace — a real routed page (the server redirects the old
	// /jarvis-agents Desk page here). Tabs deep-link: /agents/mine, /agents/
	// activity, /agents/admin; bare /agents = marketplace.
	{
		path: "/agents/:tab?",
		name: "Agents",
		component: () => import("@/views/AgentsView.vue"),
	},
	// Feature pages migrated out of the ChatView overlays (design §1.1). Each is
	// an independent top-level page reusing PageShell; the rail buttons and the
	// old `/jarvis/#skills|#macros|#filebox|#approvals` hash links route here.
	// Lazy imports of view files owned by B-pages (they may not exist until that
	// task lands — the chunk is only fetched when the route is visited).
	{ path: "/skills", name: "Skills", component: () => import("@/views/SkillsView.vue") },
	{ path: "/macros/:tab?", name: "Macros", component: () => import("@/views/MacrosView.vue") }, // tab ∈ {undefined, "runs"}
	{ path: "/files", name: "Files", component: () => import("@/views/FilesView.vue") },
	{ path: "/approvals", name: "Approvals", component: () => import("@/views/ApprovalsView.vue") },
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

export default router
