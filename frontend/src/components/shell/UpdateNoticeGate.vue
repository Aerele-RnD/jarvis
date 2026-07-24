<template>
	<!-- Full-screen release-notice gate: shown by AppShell IN PLACE OF the app
	     when this bench is behind the operator's latest jarvis version. A rendered
	     gate (not a redirect), mirroring OnboardingGate. Continue is per-session
	     only, so a fresh reload re-shows it until the tenant updates. -->
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
			<p v-else class="jv-gate-sub">A new version of {{ agentName }} is available.</p>

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

			<button class="jv-gate-btn" @click="continueSession">Continue</button>

			<p v-if="notice.currentVersion" class="jv-gate-foot">
				You're on {{ agentName }} {{ notice.currentVersion }}.
			</p>
		</div>
	</div>
</template>

<script setup>
import JarvisMark from "@/components/JarvisMark.vue";
import { agentName } from "@/branding";
import { continueSession, notice } from "@/noticeGate";
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
	margin: 0 0 22px;
	white-space: pre-line;
}

.jv-gate-link {
	display: inline-flex;
	align-items: center;
	gap: 6px;
	margin-bottom: 22px;
	font-size: 14px;
	font-weight: 500;
	color: #6e5cf6;
	text-decoration: none;
}
.jv-gate-link:hover {
	text-decoration: underline;
}

.jv-gate-btn {
	display: inline-flex;
	align-items: center;
	gap: 8px;
	padding: 10px 26px;
	border: none;
	border-radius: 9px;
	font-size: 15px;
	font-weight: 500;
	color: #fff;
	cursor: pointer;
	background: linear-gradient(135deg, #6e8bff, #8b5cf6);
	box-shadow: 0 6px 18px rgba(110, 92, 246, 0.3);
	transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.jv-gate-btn:hover {
	transform: translateY(-1px);
	box-shadow: 0 10px 24px rgba(110, 92, 246, 0.38);
}
.jv-gate-btn:active {
	transform: translateY(0);
}
.jv-gate-arrow {
	font-size: 15px;
	line-height: 1;
}

.jv-gate-foot {
	margin-top: 16px;
	font-size: 12px;
	color: var(--ink-gray-5, #9ca3af);
}
</style>
