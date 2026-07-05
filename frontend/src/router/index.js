import { createRouter, createWebHistory } from "vue-router"

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

export default router
