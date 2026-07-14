<script setup>
import { computed } from "vue"
import { useRoute, useRouter } from "vue-router"
import { store } from "../store"

// The phone's version of the desktop sidebar: the same destinations, in the same
// order, with the profile on top and settings at the foot. It used to be three
// links (Chats / Skills / Account), which is why it read as "not functioning" —
// everything the sidebar can do was simply absent.
const router = useRouter()
const route = useRoute()

const user = computed(() => window.frappe_user_id || "")
const fullName = computed(() => window.frappe_full_name || user.value)
const initial = computed(() => (fullName.value || "?").trim().charAt(0).toUpperCase())

const ICONS = {
	plus: "M12 5v14M5 12h14",
	chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
	business: "M12 2 4 7v10l8 5 8-5V7z M12 22V12M12 12 4 7M12 12l8-5",
	inbox: "M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z",
	layers: "m12 2 9 5-9 5-9-5 9-5zM3 12l9 5 9-5M3 17l9 5 9-5",
	shield: "M9 12l2 2 4-4M12 3l7 4v5c0 4.4-3 8.3-7 9-4-.7-7-4.6-7-9V7z",
	zap: "M13 2 3 14h8l-1 8 10-12h-8z",
	settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 8.9 19a1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 5 8.9a1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
}

// Same destinations as the desktop sidebar (Sidebar.vue navLinks), minus the
// ones that are genuinely desk work (Agents config, macro authoring).
const links = [
	{ label: "Chats", to: "/", icon: ICONS.chat, match: (p) => p === "/" || p.startsWith("/c/") },
	{ label: "Business", to: "/business", icon: ICONS.business },
	{ label: "File Box", to: "/files", icon: ICONS.inbox },
	{ label: "Macros", to: "/macros", icon: ICONS.layers },
	{ label: "Approvals", to: "/approvals", icon: ICONS.shield, badge: true },
	{ label: "Skills", to: "/skills", icon: ICONS.zap },
]

const isActive = (l) => (l.match ? l.match(route.path) : route.path.startsWith(l.to))

function go(to) {
	store.drawerOpen = false
	if (route.path !== to) router.push(to)
}

function newChat() {
	store.drawerOpen = false
	router.push("/c/new")
}
</script>

<template>
	<Transition name="jv-drawer">
		<div v-if="store.drawerOpen" class="jv-drawer-root">
			<div class="jv-scrim" @click="store.drawerOpen = false" />
			<aside class="jv-drawer jv-safe-top jv-safe-bottom">
				<!-- profile: tap to open the account page, exactly like the desktop
				     sidebar's UserMenu sits at the top -->
				<button class="jv-drawer-me" @click="go('/account')">
					<span class="jv-avatar">{{ initial }}</span>
					<span class="jv-me-text">
						<span class="jv-me-name">{{ fullName }}</span>
						<span class="jv-me-mail">{{ user }}</span>
					</span>
					<svg class="jv-me-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="m9 18 6-6-6-6" />
					</svg>
				</button>

				<button class="jv-drawer-new" @click="newChat">
					<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path :d="ICONS.plus" />
					</svg>
					New chat
				</button>

				<nav class="jv-drawer-nav">
					<button
						v-for="l in links"
						:key="l.to"
						class="jv-drawer-link"
						:class="{ 'is-active': isActive(l) }"
						@click="go(l.to)"
					>
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
							<path :d="l.icon" />
						</svg>
						{{ l.label }}
						<span v-if="l.badge && store.pendingApprovals" class="jv-drawer-count">
							{{ store.pendingApprovals > 9 ? "9+" : store.pendingApprovals }}
						</span>
					</button>
				</nav>

				<div class="jv-drawer-foot">
					<button class="jv-drawer-link" :class="{ 'is-active': route.path === '/settings' }" @click="go('/settings')">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
							<path :d="ICONS.settings" />
						</svg>
						Settings
					</button>
					<!-- Macro authoring, agent config and the wiki graph stay on the
					     desktop: they are desk work, not phone work. -->
					<a class="jv-drawer-link is-muted" href="/jarvis">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
							<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3" />
						</svg>
						Open full workspace
					</a>
				</div>
			</aside>
		</div>
	</Transition>
</template>

<style scoped>
.jv-drawer-root {
	position: fixed;
	inset: 0;
	z-index: 40;
}
.jv-scrim {
	position: absolute;
	inset: 0;
	background: var(--scrim);
}
.jv-drawer {
	position: absolute;
	inset: 0 auto 0 0;
	width: 284px;
	max-width: 84vw;
	display: flex;
	flex-direction: column;
	background: var(--card);
	border-right: 1px solid var(--border);
}

.jv-drawer-me {
	display: flex;
	align-items: center;
	gap: 10px;
	flex: none;
	padding: 14px 12px;
	border: 0;
	border-bottom: 1px solid var(--border);
	background: transparent;
	font: inherit;
	text-align: left;
	cursor: pointer;
}
.jv-drawer-me:active {
	background: var(--card2);
}
.jv-avatar {
	display: grid;
	place-items: center;
	width: 38px;
	height: 38px;
	flex: none;
	border-radius: 999px;
	background: linear-gradient(140deg, #8b7cf7, #6a56e8);
	color: #fff;
	font-size: 15px;
	font-weight: 600;
}
.jv-me-text {
	flex: 1;
	min-width: 0;
	display: flex;
	flex-direction: column;
}
.jv-me-name {
	font-size: 14.5px;
	font-weight: 600;
	color: var(--ink9);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.jv-me-mail {
	font-size: 12px;
	color: var(--ink5);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.jv-me-chev {
	width: 16px;
	height: 16px;
	flex: none;
	color: var(--ink3);
}

.jv-drawer-new {
	display: flex;
	align-items: center;
	justify-content: center;
	gap: 8px;
	flex: none;
	height: 44px;
	margin: 10px;
	border: 0;
	border-radius: 12px;
	background: var(--accent-solid);
	color: #fff;
	font: inherit;
	font-size: 14.5px;
	font-weight: 600;
	cursor: pointer;
}
.jv-drawer-new:active {
	opacity: 0.85;
}

.jv-drawer-nav {
	flex: 1;
	min-height: 0;
	overflow-y: auto;
	padding: 0 8px;
}
.jv-drawer-link {
	display: flex;
	align-items: center;
	gap: 12px;
	width: 100%;
	padding: 12px;
	border: 0;
	border-radius: 10px;
	background: transparent;
	color: var(--ink8);
	font: inherit;
	font-size: 15px;
	text-align: left;
	text-decoration: none;
	cursor: pointer;
}
.jv-drawer-link:active {
	background: var(--card2);
}
.jv-drawer-link.is-active {
	background: var(--accent-bg);
	color: var(--accent);
	font-weight: 600;
}
.jv-drawer-link.is-active svg {
	color: var(--accent);
}
.jv-drawer-link.is-muted {
	color: var(--ink6);
	font-size: 14px;
}
.jv-drawer-link svg {
	width: 19px;
	height: 19px;
	flex: none;
	color: var(--ink5);
}
.jv-drawer-count {
	margin-left: auto;
	min-width: 20px;
	padding: 2px 6px;
	border-radius: 999px;
	background: var(--amber-dot);
	color: #fff;
	font-size: 11px;
	font-weight: 600;
	text-align: center;
}
.jv-drawer-foot {
	flex: none;
	padding: 8px;
	border-top: 1px solid var(--border);
}

.jv-drawer-enter-active,
.jv-drawer-leave-active {
	transition: opacity 0.18s ease;
}
.jv-drawer-enter-active .jv-drawer,
.jv-drawer-leave-active .jv-drawer {
	transition: transform 0.22s cubic-bezier(0.32, 0.72, 0, 1);
}
.jv-drawer-enter-from,
.jv-drawer-leave-to {
	opacity: 0;
}
.jv-drawer-enter-from .jv-drawer,
.jv-drawer-leave-to .jv-drawer {
	transform: translateX(-100%);
}
@media (prefers-reduced-motion: reduce) {
	.jv-drawer-enter-active .jv-drawer,
	.jv-drawer-leave-active .jv-drawer {
		transition: none;
	}
}
</style>
