<template>
	<transition name="fp-drawer">
		<div v-if="modelValue" class="fp-drawer-wrap" @click.self="close">
			<aside class="fp-drawer-panel" :style="{ width: panelWidth }" role="dialog" aria-modal="true">
				<header class="fp-drawer-head">
					<div class="fp-drawer-titles">
						<div class="fp-drawer-title">{{ title }}</div>
						<div v-if="subtitle" class="fp-drawer-sub">{{ subtitle }}</div>
					</div>
					<button class="fp-btn fp-btn--icon" @click="close" title="Close" aria-label="Close">
						<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
					</button>
				</header>
				<div class="fp-drawer-body"><slot /></div>
				<footer v-if="$slots.footer" class="fp-drawer-foot"><slot name="footer" /></footer>
			</aside>
		</div>
	</transition>
</template>

<script setup>
import { computed, watch, onBeforeUnmount } from "vue"
import "@/styles/fp.css"

const props = defineProps({
	// open state (v-model)
	modelValue: { type: Boolean, default: false },
	title: { type: String, default: "" },
	subtitle: { type: String, default: "" },
	// 560 (default) or 720 per the design; Number → px, String passthrough.
	width: { type: [Number, String], default: 560 },
})
const emit = defineEmits(["update:modelValue"])

const panelWidth = computed(() => (typeof props.width === "number" ? `${props.width}px` : props.width))

function close() {
	emit("update:modelValue", false)
}

// Esc closes — listener only bound while open (mirrors the AgentsView Esc idiom).
function onKey(e) {
	if (e.key === "Escape" && props.modelValue) {
		e.stopPropagation()
		close()
	}
}
watch(
	() => props.modelValue,
	(open) => {
		if (open) window.addEventListener("keydown", onKey)
		else window.removeEventListener("keydown", onKey)
	},
)
onBeforeUnmount(() => window.removeEventListener("keydown", onKey))
</script>
