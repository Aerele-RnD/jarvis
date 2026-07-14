<script setup>
// Renders the server-built "what will change" summary (F9) for a parked gated
// write's confirmation card - replacing the raw-JSON dump. The structured card
// comes from jarvis/chat/confirm_card.py (kind = create | update | verb | email |
// method | batch_create) and is already perm-filtered + size-capped server-side.
// All values render through escaped interpolation (no v-html); the raw dry-run
// preview stays available behind a collapsed Details expander.
import { computed } from "vue"

import { verbSentence } from "@/lib/actionSummary"

const props = defineProps({
	card: { type: Object, required: true },
	// Raw preview text (pretty JSON) for the Details expander; "" hides it.
	details: { type: String, default: "" },
})

const sentence = computed(() =>
	props.card.kind === "verb" ? verbSentence(props.card) : "")
</script>

<template>
	<div class="jv-pcard">
		<!-- create: the fields the write will set -->
		<template v-if="card.kind === 'create'">
			<div class="jv-pcard-head">Create {{ card.doctype }}<template v-if="card.name"> · {{ card.name }}</template></div>
			<dl v-if="card.rows.length" class="jv-pcard-fields">
				<template v-for="(r, i) in card.rows" :key="i"><dt>{{ r.label }}</dt><dd>{{ r.value }}</dd></template>
			</dl>
			<div v-else class="jv-pcard-empty">No fields set.</div>
		</template>

		<!-- update: from -> to diff -->
		<template v-else-if="card.kind === 'update'">
			<div class="jv-pcard-head">Update {{ card.doctype }}<template v-if="card.name"> · {{ card.name }}</template></div>
			<div v-for="(d, i) in card.diff" :key="i" class="jv-pcard-diffrow">
				<span class="jv-pcard-lbl">{{ d.label }}</span>
				<span class="jv-pcard-from">{{ d.from || "(empty)" }}</span>
				<span class="jv-pcard-arrow">→</span>
				<span class="jv-pcard-to">{{ d.to || "(empty)" }}</span>
			</div>
			<div v-if="!card.diff.length" class="jv-pcard-empty">No field changes.</div>
		</template>

		<!-- verb: submit / cancel / delete / amend / apply_workflow_action -->
		<template v-else-if="card.kind === 'verb'">
			<div class="jv-pcard-verb">{{ sentence }}</div>
			<ul v-if="card.count > 1 && card.targets.length" class="jv-pcard-list">
				<li v-for="(t, i) in card.targets" :key="i">{{ t }}</li>
				<li v-if="card.extra > 0" class="jv-pcard-more">+{{ card.extra }} more</li>
			</ul>
		</template>

		<!-- email -->
		<template v-else-if="card.kind === 'email'">
			<div class="jv-pcard-kv"><span>To</span><b>{{ card.to }}</b></div>
			<div class="jv-pcard-kv"><span>Subject</span><b>{{ card.subject }}</b></div>
			<pre v-if="card.body" class="jv-pcard-body">{{ card.body }}</pre>
		</template>

		<!-- run_method -->
		<template v-else-if="card.kind === 'method'">
			<div class="jv-pcard-kv"><span>Method</span><b>{{ card.method }}</b></div>
			<dl v-if="Object.keys(card.args).length" class="jv-pcard-fields">
				<template v-for="(v, k) in card.args" :key="k"><dt>{{ k }}</dt><dd>{{ v }}</dd></template>
			</dl>
		</template>

		<!-- batch create -->
		<template v-else-if="card.kind === 'batch_create'">
			<div class="jv-pcard-head">Create {{ card.count }} record<template v-if="card.count !== 1">s</template></div>
			<ul class="jv-pcard-list">
				<li v-for="(r, i) in card.rows" :key="i">{{ r.doctype }} <b>{{ r.name }}</b></li>
				<li v-if="card.extra > 0" class="jv-pcard-more">+{{ card.extra }} more</li>
			</ul>
			<div v-for="(n, i) in card.notes" :key="'n' + i" class="jv-pcard-note">{{ n }}</div>
		</template>

		<details v-if="details" class="jv-pcard-details">
			<summary>Details</summary>
			<pre>{{ details }}</pre>
		</details>
	</div>
</template>

<style scoped>
.jv-pcard { font-size: 12.5px; color: var(--text); }
.jv-pcard-head { font-weight: 600; margin-bottom: 6px; overflow-wrap: anywhere; }
.jv-pcard-verb { font-weight: 500; overflow-wrap: anywhere; }
.jv-pcard-fields { display: grid; grid-template-columns: auto 1fr; gap: 3px 12px; margin: 0; }
.jv-pcard-fields dt { color: var(--text-3); }
.jv-pcard-fields dd { margin: 0; text-align: right; overflow-wrap: anywhere; }
.jv-pcard-diffrow { display: grid; grid-template-columns: 1fr auto auto auto; gap: 8px; align-items: baseline; padding: 2px 0; }
.jv-pcard-lbl { color: var(--text-3); }
.jv-pcard-from { color: var(--text-3); text-decoration: line-through; overflow-wrap: anywhere; }
.jv-pcard-arrow { color: var(--text-3); }
.jv-pcard-to { color: var(--green, var(--text)); font-weight: 500; overflow-wrap: anywhere; }
.jv-pcard-empty { color: var(--text-3); font-style: italic; }
.jv-pcard-kv { display: flex; justify-content: space-between; gap: 12px; padding: 2px 0; }
.jv-pcard-kv span { color: var(--text-3); }
.jv-pcard-kv b { font-weight: 500; text-align: right; overflow-wrap: anywhere; }
.jv-pcard-list { margin: 4px 0 0; padding-left: 18px; }
.jv-pcard-list li { padding: 1px 0; overflow-wrap: anywhere; }
.jv-pcard-more { list-style: none; color: var(--text-3); }
.jv-pcard-note { margin-top: 5px; color: var(--text-3); font-size: 12px; }
.jv-pcard-body { margin: 6px 0 0; padding: 8px 10px; background: var(--surface-2); border-radius: 7px; white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto; font-size: 12px; line-height: 1.5; }
.jv-pcard-details { margin-top: 8px; }
.jv-pcard-details summary { cursor: pointer; color: var(--text-3); font-size: 11.5px; user-select: none; }
.jv-pcard-details pre { margin: 6px 0 0; padding: 9px 11px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 7px; font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 11.5px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow-y: auto; }
</style>
