<script setup>
import BrandMark from "./BrandMark.vue";
import { agentName } from "@/branding";
import { continueSession, notice } from "../noticeGate";
</script>

<template>
	<!-- Full-screen overlay shown over the app while this bench is behind the
	     operator's latest jarvis version. Continue is per-session only, so a fresh
	     reload re-shows it until the tenant updates. -->
	<div class="jv-nu jv-safe-bottom">
		<div class="jv-nu-card">
			<BrandMark :size="56" />

			<span v-if="notice.latestVersion" class="jv-nu-badge"
				>Version {{ notice.latestVersion }}</span
			>

			<h1 class="jv-nu-title">{{ notice.title }}</h1>

			<p v-if="notice.message" class="jv-nu-msg">{{ notice.message }}</p>
			<p v-else class="jv-nu-msg">A new version of {{ agentName }} is available.</p>

			<a
				v-if="notice.url"
				class="jv-nu-link"
				:href="notice.url"
				target="_blank"
				rel="noopener noreferrer"
			>
				Release notes ↗
			</a>

			<button class="jv-nu-btn" @click="continueSession">Continue</button>

			<p v-if="notice.currentVersion" class="jv-nu-foot">
				You're on {{ agentName }} {{ notice.currentVersion }}.
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
.jv-nu-link {
	font-size: 14px;
	font-weight: 500;
	color: var(--accent, #6e5cf6);
	text-decoration: none;
}
.jv-nu-btn {
	margin-top: 8px;
	width: 100%;
	max-width: 260px;
	height: 48px;
	border: 0;
	border-radius: 12px;
	background: var(--accent-solid, #6e5cf6);
	color: #fff;
	font: inherit;
	font-size: 15px;
	font-weight: 600;
	cursor: pointer;
}
.jv-nu-foot {
	margin: 4px 0 0;
	font-size: 12px;
	color: var(--ink5, #9ca3af);
}
</style>
