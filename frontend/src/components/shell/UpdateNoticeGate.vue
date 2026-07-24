<template>
	<!-- Full-screen release-notice gate: AppShell renders it IN PLACE OF the app
	     while this bench is behind the operator's latest jarvis version, so chat
	     and every other feature stay out of reach until the workspace updates. A
	     rendered gate, not a redirect (mirrors OnboardingGate). No dismiss. -->
	<div class="jv-gate">
		<div class="jv-gate-bg" aria-hidden="true">
			<div class="jv-gate-orb jv-gate-orb-tl"></div>
			<div class="jv-gate-orb jv-gate-orb-br"></div>
		</div>

		<div class="jv-gate-card">
			<JarvisMark :size="56" :radius="14" class="jv-gate-logo" />

			<span v-if="notice.latestVersion" class="jv-gate-badge"
				>Version {{ notice.latestVersion }}</span
			>

			<h1 class="jv-gate-title">{{ notice.title }}</h1>

			<p v-if="notice.message" class="jv-gate-sub">{{ notice.message }}</p>

			<p class="jv-gate-block">
				Chat with {{ agentName }} is paused for this workspace until it's updated. Please
				ask your administrator to update.
			</p>

			<a
				v-if="notice.url"
				class="jv-gate-link"
				:href="notice.url"
				target="_blank"
				rel="noopener noreferrer"
			>
				Release notes
				<span class="jv-gate-arrow" aria-hidden="true">↗</span>
			</a>
		</div>
	</div>
</template>

<script setup>
import JarvisMark from "@/components/JarvisMark.vue";
import { agentName } from "@/branding";
import { notice } from "@/noticeGate";
</script>

<style scoped>
.jv-gate {
	position: relative;
	flex: 1;
	display: grid;
	place-items: center;
	width: 100%;
	height: 100%;
	overflow: hidden;
	background: var(--surface-white, #fff);
	padding: 24px;
}

.jv-gate-bg {
	position: absolute;
	inset: 0;
	pointer-events: none;
}
.jv-gate-orb {
	position: absolute;
	width: 460px;
	height: 460px;
	border-radius: 50%;
	filter: blur(40px);
	opacity: 0.5;
}
.jv-gate-orb-tl {
	top: -160px;
	left: -160px;
	background: radial-gradient(circle at 30% 30%, rgba(110, 139, 255, 0.28), transparent 70%);
}
.jv-gate-orb-br {
	bottom: -180px;
	right: -160px;
	background: radial-gradient(circle at 70% 70%, rgba(139, 92, 246, 0.24), transparent 70%);
}

.jv-gate-card {
	position: relative;
	z-index: 1;
	display: flex;
	flex-direction: column;
	align-items: center;
	text-align: center;
	max-width: 440px;
	width: 100%;
}

.jv-gate-logo {
	box-shadow: 0 8px 24px rgba(110, 92, 246, 0.28);
	margin-bottom: 20px;
}

.jv-gate-badge {
	display: inline-block;
	margin-bottom: 12px;
	padding: 3px 10px;
	border-radius: 999px;
	font-size: 12px;
	font-weight: 600;
	letter-spacing: 0.2px;
	color: #6e5cf6;
	background: rgba(110, 92, 246, 0.12);
}

.jv-gate-title {
	font-size: 24px;
	font-weight: 600;
	line-height: 1.25;
	color: var(--ink-gray-9, #171717);
	margin: 0 0 10px;
}

.jv-gate-sub {
	font-size: 15px;
	line-height: 1.55;
	color: var(--ink-gray-6, #6b7280);
	margin: 0 0 14px;
	white-space: pre-line;
}

.jv-gate-block {
	font-size: 15px;
	line-height: 1.55;
	font-weight: 500;
	color: var(--ink-gray-8, #2f2f37);
	margin: 0 0 22px;
	max-width: 400px;
}

.jv-gate-link {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	font-size: 14px;
	font-weight: 500;
	color: #6e5cf6;
	text-decoration: none;
}
.jv-gate-link:hover {
	text-decoration: underline;
}
.jv-gate-arrow {
	font-size: 15px;
	line-height: 1;
}

.jv-gate-foot {
	margin-top: 18px;
	font-size: 12px;
	color: var(--ink-gray-5, #9ca3af);
}
</style>
