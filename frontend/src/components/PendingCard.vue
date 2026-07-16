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

// The remainder line for a proposed child table. A helper rather than chained
// <template>s: with only extra_columns set, an inline chain renders a dangling
// " · ". unknown_columns MUST surface - the server counts keys it dropped rather
// than rendering them (they are not real child fields, so the save discards
// them), and a count nobody sees makes a silent drop silent again.
function tableNote(t) {
	const parts = []
	if (t.extra > 0) parts.push(`+${t.extra} more rows`)
	if (t.extra_columns > 0) parts.push(`+${t.extra_columns} more columns`)
	if (t.unknown_columns > 0)
		parts.push(`${t.unknown_columns} unrecognized field${t.unknown_columns === 1 ? "" : "s"} ignored`)
	return parts.join(" · ")
}
</script>

<template>
	<div class="jv-pcard">
		<!-- create: the fields the write will set -->
		<template v-if="card.kind === 'create'">
			<div class="jv-pcard-head">Create {{ card.doctype }}<template v-if="card.name"> · {{ card.name }}</template></div>
			<dl v-if="card.rows.length" class="jv-pcard-fields">
				<template v-for="(r, i) in card.rows" :key="i"><dt>{{ r.label }}</dt><dd>{{ r.value }}</dd></template>
			</dl>
			<div v-else-if="!(card.tables || []).length" class="jv-pcard-empty">No fields set.</div>
			<!-- proposed child tables: "5 rows" would hide an invoice's line items -->
			<div v-for="(t, ti) in (card.tables || [])" :key="'t' + ti" class="jv-pcard-table">
				<div class="jv-pcard-table-head">{{ t.label }} · {{ t.count }} row<template v-if="t.count !== 1">s</template></div>
				<div class="jv-pcard-table-scroll">
					<table>
						<thead>
							<tr><th v-for="(c, ci) in t.columns" :key="'c' + ci">{{ c }}</th></tr>
						</thead>
						<tbody>
							<tr v-for="(r, ri) in t.rows" :key="'r' + ri">
								<td v-for="(cell, di) in r.cells" :key="'d' + di">{{ cell }}</td>
							</tr>
						</tbody>
					</table>
				</div>
				<div v-if="tableNote(t)" class="jv-pcard-more">{{ tableNote(t) }}</div>
			</div>
		</template>

		<!-- update: from -> to diff -->
		<template v-else-if="card.kind === 'update'">
			<div class="jv-pcard-head">Update {{ card.doctype }}<template v-if="card.name"> · {{ card.name }}</template><template v-if="card.title"> · {{ card.title }}</template></div>
			<div v-for="(d, i) in card.diff" :key="i" class="jv-pcard-diffrow">
				<span class="jv-pcard-lbl">{{ d.label }}</span>
				<span class="jv-pcard-from">{{ d.from || "(empty)" }}</span>
				<span class="jv-pcard-arrow">→</span>
				<span class="jv-pcard-to">{{ d.to || "(empty)" }}</span>
			</div>
			<div v-if="!card.diff.length" class="jv-pcard-empty">No field changes.</div>
		</template>

		<!-- verb: submit / cancel / delete / amend / apply_workflow_action -->
		<!-- ORDER IS LOAD-BEARING: records div -> targets <ul v-else-if> -> +N more.
		     v-else-if chains to the immediately preceding sibling carrying a v-if, so
		     putting the +N more div between them would chain the <ul> to IT - and with
		     extra === 0 (always, via the F16 batch cap) every bulk card would render
		     its targets twice, once as records and once as the old list. -->
		<template v-else-if="card.kind === 'verb'">
			<div class="jv-pcard-verb">{{ sentence }}</div>
			<div v-if="(card.records || []).length" class="jv-pcard-recs">
				<template v-for="(r, i) in card.records" :key="'vr' + i">
					<details v-if="r.rows.length" class="jv-rec" :open="i === 0">
						<summary>
							<span class="jv-chev" aria-hidden="true"></span>
							<span class="jv-rec-id">{{ r.name }}</span>
							<span v-if="r.title" class="jv-rec-title">{{ r.title }}</span>
						</summary>
						<dl class="jv-pcard-fields">
							<template v-for="(f, j) in r.rows" :key="'vf' + j"><dt>{{ f.label }}</dt><dd>{{ f.value }}</dd></template>
						</dl>
					</details>
					<div v-else class="jv-rec jv-rec-bare">
						<span class="jv-rec-id">{{ r.name }}</span>
						<span v-if="r.title" class="jv-rec-title">{{ r.title }}</span>
					</div>
				</template>
			</div>
			<ul v-else-if="card.count > 1 && card.targets.length" class="jv-pcard-list">
				<li v-for="(t, i) in card.targets" :key="i">{{ t }}</li>
				<li v-if="card.extra > 0" class="jv-pcard-more">+{{ card.extra }} more</li>
			</ul>
			<div v-if="(card.records || []).length && card.extra > 0" class="jv-pcard-more">+{{ card.extra }} more</div>
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

		<!-- bulk update: one collapsible from→to preview per record -->
		<template v-else-if="card.kind === 'bulk_update'">
			<div class="jv-pcard-head">Update {{ card.count }} {{ card.doctype }} record<template v-if="card.count !== 1">s</template><span v-if="card.varying" class="jv-pcard-sub"> · varying changes</span></div>
			<p class="jv-pcard-caption">Click a record to review its changes.</p>
			<div class="jv-pcard-recs">
				<details v-for="(r, i) in card.records" :key="i" class="jv-rec" :open="i === 0">
					<summary>
						<span class="jv-chev" aria-hidden="true"></span>
						<span class="jv-rec-id">{{ r.name }}</span>
						<span v-if="r.title" class="jv-rec-title">{{ r.title }}</span>
						<span v-if="r.fields?.length" class="jv-rec-fields">{{ r.fields.join(" · ") }}</span>
					</summary>
					<div class="jv-rec-body">
						<div v-for="(d, j) in r.diff" :key="j" class="jv-pcard-diffrow">
							<span class="jv-pcard-lbl">{{ d.label }}</span>
							<span class="jv-pcard-from">{{ d.from || "(empty)" }}</span>
							<span class="jv-pcard-arrow">→</span>
							<span class="jv-pcard-to">{{ d.to || "(empty)" }}</span>
						</div>
						<div v-if="!r.diff.length" class="jv-pcard-empty">No field changes.</div>
					</div>
				</details>
			</div>
			<div v-if="card.extra > 0" class="jv-pcard-more">+{{ card.extra }} more · full list in Details</div>
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
/* create: a proposed child table, scrolling inside its own box so the card never
   scrolls the page sideways */
.jv-pcard-table { margin-top: 10px; }
.jv-pcard-table-head { font-size: 11.5px; color: var(--text-3); margin-bottom: 4px; }
.jv-pcard-table-scroll { overflow-x: auto; max-height: 240px; overflow-y: auto; }
.jv-pcard-table table { border-collapse: collapse; width: 100%; font-size: 12px; }
.jv-pcard-table th, .jv-pcard-table td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--surface-2); white-space: nowrap; }
.jv-pcard-table th { color: var(--text-3); font-weight: 500; }
.jv-pcard-table td { font-variant-numeric: tabular-nums; }
/* scoped: .jv-pcard-more is shared with the verb/batch_create <li>s */
.jv-pcard-table .jv-pcard-more { font-size: 11.5px; margin-top: 4px; }
/* bulk update: collapsible per-record from→to list */
.jv-pcard-sub { font-weight: 400; color: var(--text-3); }
.jv-pcard-caption { font-size: 11.5px; color: var(--text-3); margin: 0 0 8px; }
.jv-pcard-recs { display: flex; flex-direction: column; max-height: 320px; overflow-y: auto; overscroll-behavior: contain; -webkit-overflow-scrolling: touch; }
.jv-rec { border-top: 1px solid var(--surface-2); }
.jv-rec:first-child { border-top: none; }
.jv-rec > summary { list-style: none; cursor: pointer; display: flex; align-items: center; gap: 9px; min-height: 38px; padding: 6px 2px; border-radius: 6px; user-select: none; -webkit-tap-highlight-color: transparent; }
.jv-rec > summary::-webkit-details-marker { display: none; }
.jv-rec > summary::marker { content: ""; }
.jv-rec > summary:hover { background: var(--surface-1); }
.jv-rec > summary:focus-visible { outline: 2px solid var(--blue, var(--text)); outline-offset: -2px; }
.jv-chev { flex: none; width: 7px; height: 7px; border-right: 1.6px solid var(--text-3); border-bottom: 1.6px solid var(--text-3); transform: rotate(-45deg); transition: transform .15s ease; margin-left: 2px; }
.jv-rec[open] > summary .jv-chev { transform: rotate(45deg); }
/* verb: a name-only record (missing or unreadable) gets no expander, so it needs
   the <summary> row's metrics by hand to line up with its expandable siblings. */
.jv-rec-bare { display: flex; align-items: center; gap: 9px; min-height: 38px; padding: 6px 2px 6px 18px; }
.jv-rec-id { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 11.5px; color: var(--text); font-weight: 500; flex: none; }
.jv-rec-title { font-size: 11.5px; color: var(--text); overflow-wrap: anywhere; }
.jv-rec-fields { font-size: 11.5px; color: var(--text-3); margin-left: auto; text-align: right; overflow-wrap: anywhere; }
.jv-rec-body { padding: 2px 2px 8px 19px; }
@media (max-width: 460px) {
	.jv-rec-body .jv-pcard-diffrow { grid-template-columns: 1fr auto 1fr; }
	.jv-rec-body .jv-pcard-lbl { grid-column: 1 / -1; }
}
@media (prefers-reduced-motion: reduce) { .jv-chev { transition: none; } }
.jv-pcard-note { margin-top: 5px; color: var(--text-3); font-size: 12px; }
.jv-pcard-body { margin: 6px 0 0; padding: 8px 10px; background: var(--surface-2); border-radius: 7px; white-space: pre-wrap; word-break: break-word; max-height: 200px; overflow-y: auto; font-size: 12px; line-height: 1.5; }
.jv-pcard-details { margin-top: 8px; }
.jv-pcard-details summary { cursor: pointer; color: var(--text-3); font-size: 11.5px; user-select: none; }
.jv-pcard-details pre { margin: 6px 0 0; padding: 9px 11px; background: var(--surface-2); border: 1px solid var(--border); border-radius: 7px; font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 11.5px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow-y: auto; }
</style>
