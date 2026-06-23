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
]

// Served under /jarvis (website_route_rules catch-all → www/jarvis page).
const router = createRouter({
	history: createWebHistory("/jarvis"),
	routes,
})

export default router
