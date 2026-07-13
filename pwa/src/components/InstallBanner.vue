<script setup>
import { computed, onMounted, ref } from "vue"
import { installPrompt, isStandalone } from "../install"

// "Add Jarvis to your home screen." Two different worlds:
//  - Chrome/Android fires beforeinstallprompt. That event is captured in
//    src/install.js at module load, NOT here: it can fire in the same tick the
//    app mounts, so a listener in onMounted loses the race and the banner never
//    appears on a warm refresh. This component only reads the stashed event.
//  - iOS Safari has no such event and never will; Add to Home Screen is a manual
//    menu action, so there we can only tell the user where it is.
const DISMISS_KEY = "jarvis.install.dismissed"

const dismissed = ref(false)
const isIos = ref(false)

// Show when we either hold a real prompt (Chrome) or know we're on iOS, unless
// the user closed it or the app is already installed.
const show = computed(
	() => !dismissed.value && !isStandalone() && (!!installPrompt.value || isIos.value),
)

async function install() {
	const e = installPrompt.value
	if (!e) return
	e.prompt()
	await e.userChoice
	// The event is single-use: once prompted it cannot be replayed.
	installPrompt.value = null
}

function dismiss() {
	dismissed.value = true
	// Durable: a banner the user closed must not come back on every reload.
	try {
		localStorage.setItem(DISMISS_KEY, "1")
	} catch {
		/* private mode — a session-only dismissal is still better than none */
	}
}

onMounted(() => {
	try {
		dismissed.value = localStorage.getItem(DISMISS_KEY) === "1"
	} catch {
		/* ignore */
	}
	const ua = window.navigator.userAgent
	if (/iPhone|iPad|iPod/.test(ua) && /Safari/.test(ua) && !/CriOS|FxiOS/.test(ua)) {
		isIos.value = true
	}
})
</script>

<template>
	<Transition name="jv-install">
		<div v-if="show" class="jv-install">
			<div class="jv-mark" style="width: 34px; height: 34px; font-size: 15px">J</div>
			<div class="jv-install-text">
				<strong>Install Jarvis</strong>
				<span v-if="isIos">Tap Share, then “Add to Home Screen”.</span>
				<span v-else>Keep it one tap away, like an app.</span>
			</div>
			<button v-if="!isIos" class="jv-install-cta" @click="install">Install</button>
			<button class="jv-icon-btn" aria-label="Dismiss" @click="dismiss">
				<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
					<path d="M18 6 6 18M6 6l12 12" />
				</svg>
			</button>
		</div>
	</Transition>
</template>

<style scoped>
/* In the layout flow at the very top — NOT floating. A fixed banner has to sit
   over something: at the bottom it buries the send button and the FAB, at the
   top it buries the first message. As a flex item it pushes the app down
   instead, so it can never cover content, and the row it occupies leaves with
   it when dismissed. */
.jv-install {
	flex: none;
	display: flex;
	align-items: center;
	gap: 12px;
	margin: 8px 12px 0;
	padding: 12px;
	border-radius: 14px;
	background: var(--card);
	border: 1px solid var(--border2);
}
.jv-install-text {
	flex: 1;
	min-width: 0;
	display: flex;
	flex-direction: column;
	gap: 2px;
	font-size: 13px;
	color: var(--ink6);
	line-height: 1.35;
}
.jv-install-text strong {
	font-size: 14px;
	font-weight: 600;
	color: var(--ink9);
}
.jv-install-cta {
	flex: none;
	padding: 9px 14px;
	border: 0;
	border-radius: 9px;
	background: var(--accent-solid);
	color: #fff;
	font: inherit;
	font-size: 14px;
	font-weight: 600;
	cursor: pointer;
}
.jv-install-enter-active,
.jv-install-leave-active {
	transition: opacity 0.2s ease, transform 0.2s ease;
}
.jv-install-enter-from,
.jv-install-leave-to {
	opacity: 0;
	transform: translateY(-12px);
}
</style>
