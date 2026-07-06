import { createRouter, createWebHistory } from "vue-router"
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
	// Legacy round-2 tab routes — static, registered BEFORE :slug (§9).
	{ path: "/agents/mine", redirect: "/agents" },
	{ path: "/agents/activity", redirect: "/agents" },
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
