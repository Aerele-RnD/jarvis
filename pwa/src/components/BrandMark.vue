<script setup>
import { computed } from "vue"

// The Jarvis logo tile — identical to the native app's mark
// (jarvis_mobile/src/components/BrandMark.tsx): a violet rounded square with a
// white four-point "spark" star. This replaces the placeholder "J" the tile
// used to show in the new-chat hero, login, install banner and empty states.
// The star path is the web logo, verbatim from the native component (viewBox
// 0 0 24 24); size/radius follow the same ratios (radius 25%, star 57%).
const props = defineProps({
	size: { type: Number, default: 40 },
})

const style = computed(() => ({
	width: `${props.size}px`,
	height: `${props.size}px`,
	borderRadius: `${Math.round(props.size * 0.25)}px`,
}))
</script>

<template>
	<span class="jv-mark" :style="style">
		<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
			<path d="M12 2.5 14 10 21.5 12 14 14 12 21.5 10 14 2.5 12 10 10Z" />
		</svg>
	</span>
</template>
