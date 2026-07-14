import { createRouter, createWebHistory } from "vue-router"
import ChatsView from "./views/ChatsView.vue"

// history base = the route Frappe serves the shell at. The catch-all rule in
// hooks.py ("/jarvis-mobile/<path:app_path>") hands every deep link back to the
// same page, so a refresh on /jarvis-mobile/c/<id> resolves here rather than 404ing.
const routes = [
	{ path: "/", name: "Chats", component: ChatsView },
	{ path: "/c/:id", name: "Chat", component: () => import("./views/ChatView.vue"), props: true },
	{ path: "/skills", name: "Skills", component: () => import("./views/SkillsView.vue") },
	{ path: "/account", name: "Account", component: () => import("./views/AccountView.vue") },
	{ path: "/:pathMatch(.*)*", redirect: "/" },
]

export default createRouter({
	history: createWebHistory("/jarvis-mobile"),
	routes,
})
