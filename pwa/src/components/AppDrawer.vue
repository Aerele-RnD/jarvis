<script setup>
import { useRouter } from "vue-router"
import { store } from "../store"

const router = useRouter()

// Two kinds of approval, and they are not the same thing:
//  - a parked WRITE (action:pending) is answered in the chat that raised it —
//    the context is the conversation, so that is where the card stays;
//  - a Jarvis Approval is the agent stopping to ASK a human, and it can outlive
//    the chat session. That queue needs a home you can reach from anywhere,
//    which is here.
const links = [
	{ label: "Chats", to: "/", icon: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" },
	{
		label: "Approvals",
		to: "/approvals",
		icon: "M9 12l2 2 4-4M12 3l7 4v5c0 4.4-3 8.3-7 9-4-0.7-7-4.6-7-9V7z",
		badge: true,
	},
	{ label: "Skills", to: "/skills", icon: "M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" },
	{ label: "Account", to: "/account", icon: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z" },
]

function go(to) {
	store.drawerOpen = false
	router.push(to)
}
</script>

<template>
	<Transition name="jv-drawer">
		<div v-if="store.drawerOpen" class="jv-drawer-root">
			<div class="jv-scrim" @click="store.drawerOpen = false" />
			<aside class="jv-drawer jv-safe-top jv-safe-bottom">
				<div class="jv-drawer-head">
					<div class="jv-mark" style="width: 36px; height: 36px; font-size: 16px">J</div>
					<div>
						<div style="font-weight: 600; font-size: 15px">Jarvis</div>
						<div style="font-size: 12px; color: var(--ink5)">Your AI teammate</div>
					</div>
				</div>

				<nav class="jv-drawer-nav">
					<button v-for="l in links" :key="l.to" class="jv-drawer-link" @click="go(l.to)">
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
							<path :d="l.icon" />
						</svg>
						{{ l.label }}
						<span v-if="l.badge && store.pendingApprovals" class="jv-drawer-count">
							{{ store.pendingApprovals }}
						</span>
					</button>
				</nav>

				<!-- The phone surface is a subset by design; the full workspace
				     (macros, agents, files, settings) stays on the desktop SPA. -->
				<a class="jv-drawer-link jv-drawer-foot" href="/jarvis">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
						<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3" />
					</svg>
					Open full workspace
				</a>
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
	width: 280px;
	max-width: 82vw;
	display: flex;
	flex-direction: column;
	background: var(--card);
	border-right: 1px solid var(--border);
}
.jv-drawer-head {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 16px 16px 14px;
	border-bottom: 1px solid var(--border);
}
.jv-drawer-nav {
	flex: 1;
	min-height: 0;
	overflow-y: auto;
	padding: 8px;
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
	margin: 8px;
	border-top: 1px solid var(--border);
	border-radius: 0;
	padding-top: 16px;
	color: var(--ink6);
	font-size: 14px;
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
</style>
