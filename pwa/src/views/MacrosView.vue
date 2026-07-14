<script setup>
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import AppBar from "../components/AppBar.vue"
import * as api from "../api"
import { store } from "../store"
import { relativeTime } from "../lib/time"

// Macros: a saved sequence of prompts. Running one is a phone job ("do the
// Monday close"); authoring one is desk work, so this screen runs them and does
// not pretend to be a builder.
const router = useRouter()

const macros = ref([])
const loaded = ref(false)
const running = ref("")
const error = ref("")

async function load() {
	try {
		const rows = await api.listMacros()
		macros.value = Array.isArray(rows) ? rows : []
	} catch (e) {
		error.value = e?.message || "Couldn't load your macros."
	} finally {
		loaded.value = true
	}
}

async function run(m) {
	if (running.value) return
	running.value = m.name
	error.value = ""
	try {
		const r = await api.runMacro(m.name)
		const conv = r?.data?.conversation
		store.loadConversations()
		// A macro run IS a conversation — go and watch it work.
		if (conv) router.push(`/c/${conv}`)
		else error.value = "The macro started but didn't return a chat."
	} catch (e) {
		error.value = e?.message || "Couldn't run that macro."
	} finally {
		running.value = ""
	}
}

onMounted(load)
</script>

<template>
	<AppBar title="Macros" />

	<div class="jv-scroll">
		<div v-if="error" class="jv-err">{{ error }}</div>

		<div v-if="!loaded" class="jv-empty">Loading…</div>

		<div v-else-if="!macros.length" class="jv-empty">
			<div style="font-size: 15px; font-weight: 600; color: var(--ink9)">No macros yet</div>
			<div style="font-size: 14px; line-height: 1.5">
				A macro is a saved run of prompts — “close the month”, “chase overdue invoices”. Build one in
				the full workspace, run it from here.
			</div>
		</div>

		<ul v-else class="jv-list">
			<li v-for="m in macros" :key="m.name" class="jv-card">
				<div class="jv-card-main">
					<div class="jv-card-title">{{ m.macro_name || m.name }}</div>
					<div v-if="m.description" class="jv-card-sub">{{ m.description }}</div>
					<div class="jv-card-meta">
						{{ m.step_count || 0 }} step{{ Number(m.step_count) === 1 ? "" : "s" }}
						<template v-if="m.last_run_at"> · last run {{ relativeTime(m.last_run_at) }}</template>
						<span v-if="!m.enabled" class="jv-pill">Disabled</span>
					</div>
				</div>
				<button class="jv-run" :disabled="!m.enabled || !!running" @click="run(m)">
					<span v-if="running === m.name" class="jv-spinner" />
					<svg v-else viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
						<path d="M8 5v14l11-7z" />
					</svg>
				</button>
			</li>
		</ul>
	</div>
</template>

<style scoped>
.jv-err {
	margin: 12px 12px 0;
	font-size: 12.5px;
	color: var(--red);
}
.jv-list {
	list-style: none;
	margin: 0;
	padding: 8px;
	display: flex;
	flex-direction: column;
	gap: 6px;
}
.jv-card {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 13px 12px;
	border: 1px solid var(--border);
	border-radius: 12px;
	background: var(--card);
}
.jv-card-main {
	flex: 1;
	min-width: 0;
}
.jv-card-title {
	font-size: 14.5px;
	font-weight: 600;
	color: var(--ink9);
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.jv-card-sub {
	margin-top: 2px;
	font-size: 12.5px;
	line-height: 1.4;
	color: var(--ink5);
	display: -webkit-box;
	-webkit-line-clamp: 2;
	-webkit-box-orient: vertical;
	overflow: hidden;
}
.jv-card-meta {
	display: flex;
	align-items: center;
	gap: 6px;
	margin-top: 5px;
	font-size: 11.5px;
	color: var(--ink5);
}
.jv-pill {
	padding: 2px 7px;
	border-radius: 999px;
	background: var(--card2);
	color: var(--ink6);
	font-weight: 500;
}
.jv-run {
	display: grid;
	place-items: center;
	width: 40px;
	height: 40px;
	flex: none;
	border: 0;
	border-radius: 999px;
	background: var(--accent-bg);
	color: var(--accent);
	cursor: pointer;
}
.jv-run:disabled {
	opacity: 0.45;
	cursor: default;
}
.jv-spinner {
	width: 16px;
	height: 16px;
	border-radius: 50%;
	border: 2px solid var(--card3);
	border-top-color: var(--accent);
	animation: jv-spin 0.7s linear infinite;
}
@keyframes jv-spin {
	to {
		transform: rotate(360deg);
	}
}
</style>
