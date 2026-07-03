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
	// AI / Models config — System-Manager only; guard redirects others to Chat.
	{
		path: "/ai",
		name: "AiModels",
		component: () => import("@/views/AiView.vue"),
		beforeEnter: (to, from, next) => { next(window.is_system_manager ? undefined : { name: "Chat" }) },
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
	// only; guard redirects others to Chat. The global beforeEach below also
	// routes not-yet-onboarded System Managers here automatically.
	{
		path: "/onboarding",
		name: "Onboarding",
		component: () => import("@/views/OnboardingView.vue"),
		beforeEnter: (to, from, next) => { next(window.is_system_manager ? undefined : { name: "Chat" }) },
	},
]

// Served under /jarvis (website_route_rules catch-all → www/jarvis page).
const router = createRouter({
	history: createWebHistory("/jarvis"),
	routes,
})

// First-run guard: send a not-yet-onboarded System Manager to /onboarding on
// their first navigation, and bounce a fully-onboarded user away from
// /onboarding back to Chat. The readiness check hits the backend once per
// page load — `readyPromise` caches the in-flight/resolved call so repeated
// client-side navigations (Chat -> Account -> Chat, etc.) don't re-fire it.
// Fail-open: if the backend call throws, treat the app as ready so a flaky
// check never strands the user unable to reach Chat.
let readyPromise = null
router.beforeEach(async (to) => {
	if (!readyPromise) {
		readyPromise = isReadyForChat().catch(() => ({ ready: true }))
	}
	const ready = isOnboardComplete(await readyPromise)
	if (!ready && to.name !== "Onboarding" && window.is_system_manager) {
		return { name: "Onboarding" }
	}
	if (ready && to.name === "Onboarding") {
		return { name: "Chat" }
	}
	return true
})

export default router
