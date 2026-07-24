<script setup>
import BrandMark from "./BrandMark.vue";
import { agentName } from "@/branding";
import { notice } from "../noticeGate";
</script>

<template>
	<!-- Full-screen overlay that blocks the app while this bench is behind the
	     operator's latest jarvis version — chat stays out of reach until the
	     workspace updates. No dismiss. -->
	<div class="jv-nu jv-safe-bottom">
		<div class="jv-nu-card">
			<BrandMark :size="56" />

			<span v-if="notice.version" class="jv-nu-badge">Version {{ notice.version }}</span>

			<h1 class="jv-nu-title">A new {{ agentName }} update is available</h1>

			<p v-if="notice.message" class="jv-nu-msg">{{ notice.message }}</p>

			<p class="jv-nu-block">
				Chat with {{ agentName }} is paused for this workspace until it's updated. Please
				ask your administrator to update.
			</p>
		</div>
	</div>
</template>

<style scoped>
.jv-nu {
	position: fixed;
	inset: 0;
	z-index: 1000;
	display: flex;
	align-items: center;
	justify-content: center;
	padding: 32px 24px;
	background: var(--card, #fff);
	overflow-y: auto;
}
.jv-nu-card {
	display: flex;
	flex-direction: column;
	align-items: center;
	text-align: center;
	max-width: 360px;
	width: 100%;
	gap: 12px;
}
.jv-nu-badge {
	margin-top: 4px;
	padding: 3px 10px;
	border-radius: 999px;
	font-size: 12px;
	font-weight: 600;
	color: var(--accent, #6e5cf6);
	background: rgba(110, 92, 246, 0.12);
}
.jv-nu-title {
	margin: 2px 0 0;
	font-size: 22px;
	font-weight: 600;
	letter-spacing: -0.3px;
	color: var(--ink9, #171717);
}
.jv-nu-msg {
	margin: 0;
	font-size: 15px;
	line-height: 1.55;
	color: var(--ink6, #6b7280);
	white-space: pre-line;
}
.jv-nu-block {
	margin: 0;
	font-size: 15px;
	line-height: 1.55;
	font-weight: 500;
	color: var(--ink8, #2f2f37);
}
.jv-nu-link {
	font-size: 14px;
	font-weight: 500;
	color: var(--accent, #6e5cf6);
	text-decoration: none;
}
.jv-nu-foot {
	margin: 4px 0 0;
	font-size: 12px;
	color: var(--ink5, #9ca3af);
}
</style>
