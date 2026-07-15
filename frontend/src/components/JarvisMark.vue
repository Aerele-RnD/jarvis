<template>
	<!-- The Jarvis gradient logo mark. Single source of truth for the brand
	     glyph so the onboarding wizard, the onboarding gate poster (and any
	     future setup surface) can't drift apart on a brand refresh. -->
	<span
		class="jv-mark"
		:style="{ width: `${size}px`, height: `${size}px`, borderRadius: `${radius}px` }"
	>
		<svg :width="Math.round(size * 0.55)" :height="Math.round(size * 0.55)" viewBox="0 0 24 24" fill="#fff">
			<path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" />
		</svg>
	</span>
</template>

<script setup>
defineProps({
	size: { type: Number, default: 56 },
	radius: { type: Number, default: 14 },
})
</script>

<style scoped>
.jv-mark {
	display: grid;
	place-items: center;
	flex-shrink: 0;
	/* --brand-grad is defined on :root in main.css (theme-invariant). The literal
	   fallback keeps the mark correct if this component is ever rendered outside
	   the app's stylesheet (e.g. an isolated story or a test harness). */
	background: var(--brand-grad, linear-gradient(135deg, #6e8bff, #8b5cf6));
}
</style>
