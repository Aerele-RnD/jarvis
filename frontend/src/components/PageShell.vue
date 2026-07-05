<template>
	<div class="fp-root" :class="{ 'fp-dark': effectiveDark }" :style="paletteVars">
		<!-- ============ TOP BAR (mirrors AgentsView .ag-top) ============ -->
		<header class="fp-top">
			<router-link to="/" class="fp-brand" title="Back to chat">
				<span class="fp-logo">
					<svg width="15" height="15" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg>
				</span>
				<span class="fp-brand-txt">Jarvis</span>
			</router-link>
			<span class="fp-crumb-sep">/</span>
			<span class="fp-crumb">{{ crumb }}</span>
			<div style="flex:1;"></div>
			<router-link to="/" class="fp-btn fp-btn--ghost fp-btn--sm">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
				Back to chat
			</router-link>
			<button class="fp-btn fp-btn--icon" @click="toggleTheme" :title="effectiveDark ? 'Switch to light theme' : 'Switch to dark theme'">
				<svg v-if="effectiveDark" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
				<svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
			</button>
		</header>

		<!-- ============ PAGE HEAD: title + subtitle + actions + tabs ============ -->
		<div class="fp-head">
			<div class="fp-head-in">
				<div class="fp-head-row">
					<div class="fp-head-titles">
						<h1 class="fp-title">{{ title }}</h1>
						<p v-if="subtitle" class="fp-sub">{{ subtitle }}</p>
					</div>
					<div v-if="$slots.actions" class="fp-head-actions"><slot name="actions" /></div>
				</div>
				<nav v-if="tabs.length" class="fp-tabs" role="tablist">
					<button v-for="t in tabs" :key="t.id" class="fp-tab" :class="{ on: modelValue === t.id }" role="tab" :aria-selected="String(modelValue === t.id)" @click="goTab(t.id)">
						{{ t.label }}<span v-if="t.count != null" class="fp-tab-n">{{ t.count }}</span>
					</button>
				</nav>
			</div>
		</div>

		<!-- ============ CONTENT ============ -->
		<main class="fp-main">
			<div class="fp-content">
				<div v-if="$slots.banner" class="fp-banner"><slot name="banner" /></div>
				<slot />
			</div>
		</main>

		<!-- ============ TOASTS (shared singleton) ============ -->
		<div class="fp-notes" aria-live="polite">
			<transition-group name="fp-note">
				<div v-for="n in notes" :key="n.id" class="fp-note" :class="n.type" role="status">
					<span class="fp-note-ic" aria-hidden="true">
						<svg v-if="n.type === 'success'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
						<svg v-else-if="n.type === 'error'" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 8v5M12 16.4v.01" /></svg>
						<svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 16v-5M12 8v.01" /></svg>
					</span>
					<div class="fp-note-msg">{{ n.message }}</div>
					<button class="fp-note-x" @click="dismissNote(n.id)" title="Dismiss" aria-label="Dismiss"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg></button>
				</div>
			</transition-group>
		</div>

		<!-- ============ CONFIRM DIALOG (shared singleton) ============ -->
		<transition name="fp-fade">
			<div v-if="confirmBox" class="fp-overlay" @click.self="settleConfirm(false)">
				<div class="fp-cdialog" role="alertdialog" aria-modal="true">
					<div class="fp-cdialog-title">{{ confirmBox.title }}</div>
					<div v-if="confirmBox.message" class="fp-cdialog-msg">{{ confirmBox.message }}</div>
					<div class="fp-cdialog-foot">
						<button class="fp-btn fp-btn--ghost" @click="settleConfirm(false)">Cancel</button>
						<button class="fp-btn fp-btn--danger" @click="settleConfirm(true)">{{ confirmBox.confirmLabel }}</button>
					</div>
				</div>
			</div>
		</transition>
	</div>
</template>

<script setup>
import { onMounted, onBeforeUnmount, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { useJarvisTheme } from "@/theme"
import { useNotify } from "@/composables/useNotify"
import "@/styles/fp.css"

const props = defineProps({
	crumb: { type: String, default: "" },
	title: { type: String, default: "" },
	subtitle: { type: String, default: "" },
	// Optional deep-linkable tabs: [{ id, label, count? }] routed like AgentsView.
	tabs: { type: Array, default: () => [] },
	// Base route path for tab routing, e.g. "/macros". The tab whose id === defaultTab
	// maps to the bare basePath; others map to `${basePath}/${id}`.
	basePath: { type: String, default: "" },
	defaultTab: { type: String, default: "" },
	// Active tab id (v-model); PageShell keeps it in sync with route.params.tab.
	modelValue: { type: String, default: "" },
})
const emit = defineEmits(["update:modelValue", "esc"])

const route = useRoute()
const router = useRouter()
const { effectiveDark, paletteVars, toggleTheme } = useJarvisTheme()
const { notes, dismissNote, confirmBox, settleConfirm } = useNotify()

// ── tab routing (deep-linkable, mirrors AgentsView.vue:525-545) ─────────────
function pathFor(id) {
	if (!props.basePath) return "/"
	return !id || id === props.defaultTab ? props.basePath : `${props.basePath}/${id}`
}
function goTab(id) {
	if (id === props.modelValue) return
	router.push(pathFor(id))
}
function syncTab() {
	if (!props.tabs.length) return
	const t = route.params.tab || props.defaultTab || props.tabs[0].id
	if (!props.tabs.some((x) => x.id === t)) {
		router.replace(props.basePath || "/")
		return
	}
	if (t !== props.modelValue) emit("update:modelValue", t)
}
watch(() => route.params.tab, syncTab)

// ── Esc: close the confirm dialog first; otherwise let the page react ───────
function onKey(e) {
	if (e.key !== "Escape") return
	if (confirmBox.value) settleConfirm(false)
	else emit("esc")
}
onMounted(() => {
	syncTab()
	window.addEventListener("keydown", onKey)
})
onBeforeUnmount(() => {
	window.removeEventListener("keydown", onKey)
})
</script>
