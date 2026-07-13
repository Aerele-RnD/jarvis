<script setup>
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import * as api from "../api"

const router = useRouter()
const skills = ref([])
const loaded = ref(false)

onMounted(async () => {
	try {
		const rows = await api.listCustomSkills()
		skills.value = Array.isArray(rows) ? rows : rows?.skills || []
	} catch (e) {
		console.error("Jarvis PWA: failed to load skills", e)
	} finally {
		loaded.value = true
	}
})
</script>

<template>
	<div class="jv-bar">
		<button class="jv-icon-btn" aria-label="Back" @click="router.push('/')">
			<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
				<path d="m15 18-6-6 6-6" />
			</svg>
		</button>
		<div class="jv-title">Skills</div>
	</div>

	<div class="jv-scroll">
		<div v-if="!loaded" class="jv-empty">Loading…</div>

		<div v-else-if="!skills.length" class="jv-empty">
			<div style="font-size: 15px; font-weight: 600; color: var(--ink9)">No skills yet</div>
			<div style="font-size: 14px; line-height: 1.5">
				Skills teach Jarvis how your business does things. Create them in the full workspace.
			</div>
		</div>

		<!-- Read-only on the phone by design: authoring a skill is a desk job. -->
		<ul v-else class="jv-cards">
			<li v-for="s in skills" :key="s.name" class="jv-card">
				<div class="jv-card-title">{{ s.title || s.skill_name || s.name }}</div>
				<div v-if="s.description" class="jv-card-sub">{{ s.description }}</div>
			</li>
		</ul>
	</div>
</template>

<style scoped>
.jv-cards {
	list-style: none;
	margin: 0;
	padding: 8px;
	display: flex;
	flex-direction: column;
	gap: 6px;
}
.jv-card {
	padding: 14px 12px;
	border: 1px solid var(--border);
	border-radius: 12px;
	background: var(--card);
}
.jv-card-title {
	font-size: 15px;
	font-weight: 500;
	color: var(--ink9);
}
.jv-card-sub {
	margin-top: 4px;
	font-size: 13px;
	line-height: 1.45;
	color: var(--ink5);
}
</style>
