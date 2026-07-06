<template>
	<FrappeUIProvider>
		<div class="flex h-screen w-screen">
			<div class="h-full border-r bg-surface-gray-1">
				<Sidebar />
			</div>
			<div class="flex flex-1 flex-col h-full overflow-auto bg-surface-white">
				<!-- LayoutHeader teleport target — non-chat routes only (D41) -->
				<div v-if="!route.meta.chat" class="flex border-b">
					<div id="app-header" class="flex-1" />
				</div>
				<router-view v-if="booted" />
			</div>
			<Dialogs />
			<JarvisCommandPalette />
		</div>
	</FrappeUIProvider>
</template>

<script setup>
// App shell (DESIGN-V3 §3.1): persistent sidebar around every route, the
// #app-header strip, the confirmDialog host, the ⌘K palette, the onboarding
// gate (D11), the approvals-badge poll (D12) and the global shortcuts.
import { onMounted, onBeforeUnmount, ref } from "vue"
import { useRoute, useRouter } from "vue-router"
import { FrappeUIProvider, Dialogs, setConfig } from "frappe-ui"
import * as api from "@/api"
import { useShellStore } from "@/stores/shell"
import { useShortcuts } from "@/composables/useShortcuts"
import Sidebar from "./Sidebar.vue"
import JarvisCommandPalette from "./JarvisCommandPalette.vue"

const route = useRoute()
const router = useRouter()
const store = useShellStore()

// Boot gate: hold the routed page (NOT the shell chrome) until systemTimezone
// is configured — timeAgo strings render once, so a late setConfig would leave
// stale future-tense timestamps on the first paint. Production boot injects
// window.time_zone via jinjaBootData (www/jarvis.py), so this is synchronous;
// the awaited getChatUiSettings read in onMounted is only the dev-server /
// missing-key fallback.
const booted = ref(false)
if (typeof window !== "undefined" && window.time_zone) {
	setConfig("systemTimezone", window.time_zone)
	booted.value = true
}

// Global shortcuts (§3.1). ⌘K moved here from the stock CommandPalette —
// JarvisCommandPalette is now built on plain Dialog and owns no keys itself
// (the stock component never mounted its Dialog subtree; DA-06 died with it).
useShortcuts([
	{ key: "o", ctrl: true, shift: true, handler: () => store.requestNewChat(router) },
	{ key: "b", ctrl: true, handler: () => (store.sidebarCollapsed = !store.sidebarCollapsed) },
	{ key: "k", meta: true, handler: () => (store.paletteOpen = !store.paletteOpen) },
])

// Badge upkeep (D12): mount · route change · visibility (2s debounce) · 60s
// interval while the tab is visible.
let _interval = null
function startInterval() {
	if (_interval) return
	_interval = setInterval(() => store.refreshApprovalsCount(), 60000)
}
function stopInterval() {
	if (_interval) {
		clearInterval(_interval)
		_interval = null
	}
}
let _visTimer = null
function onVisibility() {
	if (document.visibilityState === "visible") {
		startInterval()
		clearTimeout(_visTimer)
		_visTimer = setTimeout(() => store.refreshApprovalsCount(), 2000)
	} else {
		stopInterval()
	}
}
const removeAfterEach = router.afterEach(() => store.refreshApprovalsCount())

onMounted(async () => {
	document.addEventListener("visibilitychange", onVisibility)
	if (document.visibilityState === "visible") startInterval()

	// Sidebar fills without ChatView needing to be mounted (§3.1).
	store.loadConversations()
	store.refreshApprovalsCount()

	// Fallback only (vite dev server serves index.html without the jinja boot
	// injection, and older cached shells may miss the key): fetch the timezone
	// the old way before revealing the routed page. In production this branch
	// never runs — booted flipped synchronously in setup above.
	if (!booted.value) {
		try {
			const res = await api.getChatUiSettings()
			if (res?.time_zone) setConfig("systemTimezone", res.time_zone)
		} catch {
			// fall through — dayjsLocal degrades to browser-local parsing
		}
		booted.value = true
	}

	// Onboarding gate (D11) — ran per-route in ChatView before; now every
	// page load checks once. A transient failure falls through to the app
	// rather than trapping the user.
	const r = await api.isReadyForChat().catch(() => null)
	if (r && r.ready === false) {
		window.location.assign("/app/jarvis-onboarding")
	}
})

onBeforeUnmount(() => {
	document.removeEventListener("visibilitychange", onVisibility)
	clearTimeout(_visTimer)
	stopInterval()
	removeAfterEach()
})
</script>
