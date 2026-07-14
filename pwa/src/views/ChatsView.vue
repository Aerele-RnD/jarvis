<script setup>
import { onMounted } from "vue"
import { useRouter } from "vue-router"
import { store } from "../store"
import { relativeTime } from "../lib/time"

const router = useRouter()

// New chat = navigate to the thread with no id. send_message creates (or
// focuses) the empty conversation server-side on the first send, so we don't
// spend a round-trip creating one the user might never type into.
function newChat() {
	router.push("/c/new")
}

onMounted(() => {
	if (!store.loaded) store.loadConversations()
})
</script>

<template>
	<div class="jv-bar">
		<button class="jv-icon-btn" aria-label="Menu" @click="store.drawerOpen = true">
			<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
				<path d="M3 6h18M3 12h18M3 18h18" />
			</svg>
		</button>
		<div class="jv-title">Chats</div>
		<button class="jv-icon-btn" aria-label="New chat" @click="newChat">
			<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
				<path d="M12 5v14M5 12h14" />
			</svg>
		</button>
	</div>

	<div class="jv-scroll">
		<div v-if="!store.loaded" class="jv-empty">Loading…</div>

		<div v-else-if="!store.conversations.length" class="jv-empty">
			<div class="jv-mark" style="width: 52px; height: 52px; font-size: 21px">J</div>
			<div style="font-size: 16px; font-weight: 600; color: var(--ink9)">Ask Jarvis anything</div>
			<div style="font-size: 14px; line-height: 1.5">
				Invoices, stock, customers, reports — in plain language. Start a chat and see.
			</div>
		</div>

		<ul v-else class="jv-list">
			<li v-for="c in store.conversations" :key="c.name">
				<button class="jv-row" @click="router.push(`/c/${c.name}`)">
					<div class="jv-row-main">
						<div class="jv-row-title">{{ c.title || "New chat" }}</div>
						<div class="jv-row-time">{{ relativeTime(c.modified) }}</div>
					</div>
					<svg class="jv-row-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="m9 18 6-6-6-6" />
					</svg>
				</button>
			</li>
		</ul>
	</div>

	<!-- The native app has no tab bar (chats is the only destination), so the
	     FAB is the primary action here too. -->
	<button class="jv-fab jv-safe-bottom" aria-label="New chat" @click="newChat">
		<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
			<path d="M12 5v14M5 12h14" />
		</svg>
	</button>
</template>

<style scoped>
.jv-list {
	list-style: none;
	margin: 0;
	padding: 8px;
	display: flex;
	flex-direction: column;
	gap: 6px;
}
.jv-row {
	display: flex;
	align-items: center;
	gap: 10px;
	width: 100%;
	padding: 14px 12px;
	border: 1px solid var(--border);
	border-radius: 12px;
	background: var(--card);
	font: inherit;
	text-align: left;
	cursor: pointer;
}
.jv-row:active {
	background: var(--card2);
}
.jv-row-main {
	flex: 1;
	min-width: 0;
}
.jv-row-title {
	font-size: 15px;
	font-weight: 500;
	color: var(--ink9);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.jv-row-time {
	margin-top: 3px;
	font-size: 12px;
	color: var(--ink5);
}
.jv-row-chev {
	width: 16px;
	height: 16px;
	flex: none;
	color: var(--ink3);
}
.jv-fab {
	position: fixed;
	right: 18px;
	bottom: 18px;
	width: 54px;
	height: 54px;
	display: grid;
	place-items: center;
	border: 0;
	border-radius: 50%;
	background: var(--accent-solid);
	color: #fff;
	box-shadow: 0 8px 24px rgba(113, 84, 245, 0.4);
	cursor: pointer;
}
.jv-fab:active {
	transform: scale(0.95);
}
</style>
