<script setup>
import { computed } from "vue";
import { brandLogoUrl } from "@/branding";

// The Jarvis logo tile — identical to the native app's mark
// (jarvis_mobile/src/components/BrandMark.tsx): a violet rounded square with a
// white four-point "spark" star. This replaces the placeholder "J" the tile
// used to show in the new-chat hero, login, install banner and empty states.
// The star path is the web logo, verbatim from the native component (viewBox
// 0 0 24 24); size/radius follow the same ratios (radius 25%, star 57%).
// When the tenant has uploaded a whitelabel logo we render it in place.
//
// `mood="upgrading"` (Stream E): while this tenant's agent is being upgraded the
// tile shows a sleepy face — heavy drooping lids + a soft "z z z" — the mobile
// twin of the desktop JarvisMark's "upgrading" mood, so the character reads the
// same "resting, back shortly" on both surfaces. The whitelabel <img> branch
// ignores mood (a tenant logo stays put; the top-of-app hold strip carries the
// message there), matching the desktop mark.
const props = defineProps({
	size: { type: Number, default: 40 },
	mood: {
		type: String,
		default: "star",
		validator: (v) => ["star", "upgrading"].includes(v),
	},
});

const style = computed(() => ({
	width: `${props.size}px`,
	height: `${props.size}px`,
	borderRadius: `${Math.round(props.size * 0.25)}px`,
	"--sz": `${props.size}px`,
}));
</script>

<template>
	<img
		v-if="brandLogoUrl"
		:src="brandLogoUrl"
		class="jv-mark jv-mark-img"
		:style="style"
		alt=""
	/>
	<span v-else class="jv-mark" :class="{ 'jv-mark-up': mood === 'upgrading' }" :style="style">
		<!-- Upgrading: sleepy lids + z z z (kept inside the tile, which clips its
		     corners). The star (the ::before mask) is hidden while this shows. -->
		<template v-if="mood === 'upgrading'">
			<span class="bm-face" aria-hidden="true"
				><i class="bm-eye"></i><i class="bm-eye"></i
			></span>
			<span class="bm-zzz" aria-hidden="true"><i>z</i><i>z</i><i>z</i></span>
		</template>
		<svg v-else viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
			<path d="M12 2.5 14 10 21.5 12 14 14 12 21.5 10 14 2.5 12 10 10Z" />
		</svg>
	</span>
</template>

<style scoped>
.jv-mark-img {
	object-fit: cover;
	display: block;
	flex-shrink: 0;
}

/* Upgrading: hide the masked star (the global .jv-mark::before) so only the face
   shows. Higher specificity than the global rule, so display:none wins. */
.jv-mark-up::before {
	display: none;
}
/* Sleepy white pill eyes, the mobile twin of JarvisMark's "upgrading" mood
   (same .135/.2 proportions, drooped to heavy lids). #fff explicitly — the tile
   sets color:transparent, which would otherwise blank a currentColor fill. */
.bm-face {
	position: absolute;
	inset: 0;
	display: flex;
	align-items: center;
	justify-content: center;
	gap: calc(var(--sz) * 0.19);
	animation: bm-breathe 4.6s ease-in-out infinite;
}
.bm-eye {
	width: calc(var(--sz) * 0.135);
	height: calc(var(--sz) * 0.055);
	background: #fff;
	border-radius: 999px;
	animation: bm-lid 4.6s ease-in-out infinite;
}
.bm-eye:first-child {
	transform: rotate(-13deg);
}
.bm-eye:last-child {
	transform: rotate(13deg);
}
@keyframes bm-breathe {
	0%,
	100% {
		transform: scale(0.99);
	}
	50% {
		transform: scale(1.02);
	}
}
@keyframes bm-lid {
	0%,
	100% {
		height: calc(var(--sz) * 0.055);
	}
	50% {
		height: calc(var(--sz) * 0.022);
	}
}
/* The sleep "z z z", white on the gradient, rising and fading in the corner.
   Bounded travel so it fades before the tile's clipped edge. */
.bm-zzz {
	position: absolute;
	top: 9%;
	right: 8%;
	display: flex;
	align-items: flex-end;
	gap: 1px;
	line-height: 1;
	pointer-events: none;
}
.bm-zzz i {
	font-style: normal;
	font-weight: 800;
	color: #fff;
	opacity: 0;
}
.bm-zzz i:nth-child(1) {
	font-size: calc(var(--sz) * 0.13);
	animation: bm-z 3.2s ease-out infinite;
}
.bm-zzz i:nth-child(2) {
	font-size: calc(var(--sz) * 0.17);
	animation: bm-z 3.2s ease-out 0.6s infinite;
}
.bm-zzz i:nth-child(3) {
	font-size: calc(var(--sz) * 0.22);
	animation: bm-z 3.2s ease-out 1.2s infinite;
}
@keyframes bm-z {
	0% {
		opacity: 0;
		transform: translateY(20%) scale(0.7);
	}
	30% {
		opacity: 0.85;
	}
	100% {
		opacity: 0;
		transform: translateY(-30%) scale(1.05);
	}
}
@media (prefers-reduced-motion: reduce) {
	.bm-face,
	.bm-eye,
	.bm-zzz i {
		animation: none;
	}
	.bm-zzz i {
		opacity: 0.8;
	}
}
</style>
