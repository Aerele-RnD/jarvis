<script setup>
// Renders the server-built "what will change" summary (F9) for a parked write's
// approval sheet - replacing the raw-JSON dump. The structured card comes from
// jarvis/chat/confirm_card.py (kind = create | update | verb | email | method |
// batch_create), already perm-filtered + size-capped + secret-masked server-side.
// Logic (verbSentence) is the SAME helper the desktop uses (@shared). All values
// render as escaped text; the raw dry-run JSON stays behind a Details expander.
import { computed } from "vue"

import { verbSentence } from "@shared/lib/actionSummary.js"

const props = defineProps({
	card: { type: Object, required: true },
	details: { type: String, default: "" },
})

const sentence = computed(() =>
	props.card.kind === "verb" ? verbSentence(props.card) : "")
</script>

<template>
	<div class="jv-pc">
		<template v-if="card.kind === 'create'">
			<div class="jv-pc-head">Create {{ card.doctype }}<template v-if="card.name"> · {{ card.name }}</template></div>
			<div v-for="(r, i) in card.rows" :key="i" class="jv-pc-kv"><span>{{ r.label }}</span><b>{{ r.value }}</b></div>
			<div v-if="!card.rows.length" class="jv-pc-empty">No fields set.</div>
		</template>

		<template v-else-if="card.kind === 'update'">
			<div class="jv-pc-head">Update {{ card.doctype }}<template v-if="card.name"> · {{ card.name }}</template></div>
			<div v-for="(d, i) in card.diff" :key="i" class="jv-pc-diff">
				<span class="jv-pc-lbl">{{ d.label }}</span>
				<span class="jv-pc-from">{{ d.from || "(empty)" }}</span>
				<span class="jv-pc-arrow">→</span>
				<span class="jv-pc-to">{{ d.to || "(empty)" }}</span>
			</div>
			<div v-if="!card.diff.length" class="jv-pc-empty">No field changes.</div>
		</template>

		<template v-else-if="card.kind === 'verb'">
			<div class="jv-pc-verb">{{ sentence }}</div>
			<ul v-if="card.count > 1 && card.targets.length" class="jv-pc-list">
				<li v-for="(t, i) in card.targets" :key="i">{{ t }}</li>
				<li v-if="card.extra > 0" class="jv-pc-more">+{{ card.extra }} more</li>
			</ul>
		</template>

		<template v-else-if="card.kind === 'email'">
			<div class="jv-pc-kv"><span>To</span><b>{{ card.to }}</b></div>
			<div class="jv-pc-kv"><span>Subject</span><b>{{ card.subject }}</b></div>
			<pre v-if="card.body" class="jv-pc-body">{{ card.body }}</pre>
		</template>

		<template v-else-if="card.kind === 'method'">
			<div class="jv-pc-kv"><span>Method</span><b>{{ card.method }}</b></div>
			<div v-for="(v, k) in card.args" :key="k" class="jv-pc-kv"><span>{{ k }}</span><b>{{ v }}</b></div>
		</template>

		<template v-else-if="card.kind === 'batch_create'">
			<div class="jv-pc-head">Create {{ card.count }} record<template v-if="card.count !== 1">s</template></div>
			<ul class="jv-pc-list">
				<li v-for="(r, i) in card.rows" :key="i">{{ r.doctype }} <b>{{ r.name }}</b></li>
				<li v-if="card.extra > 0" class="jv-pc-more">+{{ card.extra }} more</li>
			</ul>
			<div v-for="(n, i) in card.notes" :key="'n' + i" class="jv-pc-note">{{ n }}</div>
		</template>

		<details v-if="details" class="jv-pc-details">
			<summary>Details</summary>
			<pre>{{ details }}</pre>
		</details>
	</div>
</template>

<style scoped>
.jv-pc { font-size: 13px; color: var(--ink7); line-height: 1.5; }
.jv-pc-head { font-weight: 600; color: var(--ink9); margin-bottom: 6px; overflow-wrap: anywhere; }
.jv-pc-verb { font-weight: 500; color: var(--ink9); overflow-wrap: anywhere; }
.jv-pc-kv { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; border-bottom: 1px solid var(--border); }
.jv-pc-kv:last-child { border-bottom: 0; }
.jv-pc-kv span { color: var(--ink5); }
.jv-pc-kv b { font-weight: 500; color: var(--ink8); text-align: right; overflow-wrap: anywhere; }
.jv-pc-diff { display: grid; grid-template-columns: 1fr auto auto auto; gap: 8px; align-items: baseline; padding: 3px 0; }
.jv-pc-lbl { color: var(--ink5); }
.jv-pc-from { color: var(--ink5); text-decoration: line-through; overflow-wrap: anywhere; }
.jv-pc-arrow { color: var(--ink5); }
.jv-pc-to { color: var(--green, var(--ink9)); font-weight: 500; overflow-wrap: anywhere; }
.jv-pc-empty { color: var(--ink5); font-style: italic; }
.jv-pc-list { margin: 5px 0 0; padding-left: 18px; }
.jv-pc-list li { padding: 1px 0; overflow-wrap: anywhere; }
.jv-pc-more { list-style: none; color: var(--ink5); }
.jv-pc-note { margin-top: 6px; color: var(--ink5); font-size: 12.5px; }
.jv-pc-body { margin: 8px 0 0; padding: 10px; border-radius: 8px; background: var(--card2); color: var(--ink7); font-size: 12.5px; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow-y: auto; }
.jv-pc-details { margin-top: 10px; }
.jv-pc-details summary { cursor: pointer; color: var(--ink5); font-size: 12px; }
.jv-pc-details pre { margin: 6px 0 0; padding: 10px; border-radius: 8px; background: var(--card2); font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow-y: auto; }
</style>
