<script setup>
import { onMounted, onUnmounted, inject } from "vue"
import { useRouter } from "vue-router"
import AppDrawer from "./components/AppDrawer.vue"
import InstallBanner from "./components/InstallBanner.vue"
import { store } from "./store"

const socket = inject("$socket")
const router = useRouter()

// Chat-list-level realtime. The per-message stream is handled inside ChatView;
// these two kinds have to land even when the user is NOT in that chat, so they
// live at the shell: a chat titles itself after its first turn, and Jarvis can
// open a conversation on its own (proactive greeting).
function onEvent(p) {
	if (p.kind === "conversation:renamed" && p.conversation_id) {
		store.applyRename(p.conversation_id, p.title)
	} else if (p.kind === "conversation:new") {
		store.loadConversations()
	}
}

// socket.io has no replay: frames published while the phone was asleep or the
// socket was down are simply gone. Refetch on reconnect and on tab-wake rather
// than trusting the stream — the same contract the desktop SPA follows.
function onResync() {
	store.loadConversations()
	if (router.currentRoute.value.name === "Chat") window.dispatchEvent(new Event("jv:resync"))
}
function onVisibility() {
	if (document.visibilityState === "visible") onResync()
}

onMounted(() => {
	socket?.on("jarvis:event", onEvent)
	socket?.on("connect", onResync)
	document.addEventListener("visibilitychange", onVisibility)
})
onUnmounted(() => {
	socket?.off("jarvis:event", onEvent)
	socket?.off("connect", onResync)
	document.removeEventListener("visibilitychange", onVisibility)
})
</script>

<template>
	<div class="jv-app">
		<!-- First child, in the flow: the install strip pushes the app down rather
		     than covering any part of it. -->
		<InstallBanner />
		<router-view v-slot="{ Component }">
			<component :is="Component" />
		</router-view>
		<AppDrawer />
	</div>
</template>
