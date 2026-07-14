<script setup>
import { computed, onMounted, ref } from "vue"
import { call } from "frappe-ui"
import AppBar from "../components/AppBar.vue"
import * as api from "../api"
import { applyTheme, theme } from "../lib/theme"

const settings = ref(null)
const signingOut = ref(false)

const THEMES = [
	{ value: "system", label: "System" },
	{ value: "light", label: "Light" },
	{ value: "dark", label: "Dark" },
]

// The bench-wide default. Per-chat overrides live in the chat's own menu — this
// screen only reports what a new chat will use, rather than pretending the phone
// can set the tenant's default (it can't: that's Jarvis Settings, admin work).
const defaultModel = computed(() => settings.value?.llm_model || "—")
const provider = computed(() => settings.value?.llm_provider || "—")
const stt = computed(() => (settings.value?.stt_enabled ? "On" : "Off"))
const timeZone = computed(() => settings.value?.time_zone || "—")

async function signOut() {
	if (signingOut.value) return
	signingOut.value = true
	try {
		await call("logout")
	} catch {
		// Session may already be gone; leave for the login screen either way.
	}
	window.location.href = "/jarvis-mobile/login"
}

onMounted(async () => {
	try {
		settings.value = await api.getChatUiSettings()
	} catch {
		/* the screen is still useful without it */
	}
})
</script>

<template>
	<AppBar title="Settings" />

	<div class="jv-scroll">
		<div class="jv-group">
			<div class="jv-group-label">Appearance</div>
			<div class="jv-seg">
				<button
					v-for="t in THEMES"
					:key="t.value"
					class="jv-seg-btn"
					:class="{ 'is-on': theme === t.value }"
					@click="applyTheme(t.value)"
				>
					{{ t.label }}
				</button>
			</div>
		</div>

		<div class="jv-group">
			<div class="jv-group-label">Assistant</div>
			<div class="jv-rows">
				<div class="jv-row">
					<span>Default model</span>
					<strong>{{ defaultModel }}</strong>
				</div>
				<div class="jv-row">
					<span>Provider</span>
					<strong>{{ provider }}</strong>
				</div>
				<div class="jv-row">
					<span>Dictation</span>
					<strong>{{ stt }}</strong>
				</div>
				<div class="jv-row">
					<span>Time zone</span>
					<strong>{{ timeZone }}</strong>
				</div>
			</div>
			<p class="jv-note">
				Change the model for a single chat from that chat's menu. The default here is set for the
				whole workspace.
			</p>
		</div>

		<div class="jv-group">
			<div class="jv-group-label">Account</div>
			<div class="jv-actions">
				<a class="jv-action" href="/jarvis">Open full workspace</a>
				<button class="jv-action is-danger" :disabled="signingOut" @click="signOut">
					{{ signingOut ? "Signing out…" : "Sign out" }}
				</button>
			</div>
		</div>
	</div>
</template>

<style scoped>
.jv-group {
	padding: 16px 12px 4px;
}
.jv-group-label {
	margin-bottom: 8px;
	font-size: 11px;
	font-weight: 600;
	letter-spacing: 0.4px;
	text-transform: uppercase;
	color: var(--ink5);
}
.jv-seg {
	display: flex;
	gap: 4px;
	padding: 4px;
	border: 1px solid var(--border);
	border-radius: 12px;
	background: var(--card);
}
.jv-seg-btn {
	flex: 1;
	height: 38px;
	border: 0;
	border-radius: 9px;
	background: transparent;
	color: var(--ink6);
	font: inherit;
	font-size: 14px;
	font-weight: 500;
	cursor: pointer;
}
.jv-seg-btn.is-on {
	background: var(--accent-bg);
	color: var(--accent);
	font-weight: 600;
}
.jv-rows {
	border: 1px solid var(--border);
	border-radius: 12px;
	background: var(--card);
	overflow: hidden;
}
.jv-row {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 12px;
	padding: 13px 12px;
	border-bottom: 1px solid var(--border);
	font-size: 14px;
	color: var(--ink6);
}
.jv-row:last-child {
	border-bottom: 0;
}
.jv-row strong {
	font-weight: 600;
	color: var(--ink9);
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.jv-note {
	margin: 8px 2px 0;
	font-size: 12.5px;
	line-height: 1.45;
	color: var(--ink5);
}
.jv-actions {
	display: flex;
	flex-direction: column;
	gap: 6px;
	padding-bottom: 20px;
}
.jv-action {
	display: block;
	width: 100%;
	padding: 14px 12px;
	border: 1px solid var(--border);
	border-radius: 12px;
	background: var(--card);
	color: var(--ink8);
	font: inherit;
	font-size: 15px;
	text-align: center;
	text-decoration: none;
	cursor: pointer;
}
.jv-action.is-danger {
	color: var(--red);
}
.jv-action:disabled {
	opacity: 0.6;
}
</style>
