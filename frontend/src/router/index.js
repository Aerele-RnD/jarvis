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
]

// Served under /jarvis (website_route_rules catch-all → www/jarvis page).
const router = createRouter({
	history: createWebHistory("/jarvis"),
	routes,
})

export default router
