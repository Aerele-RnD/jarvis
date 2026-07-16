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

// The remainder line for a proposed child table. Duplicated from the desktop card
// rather than shared: the two TEMPLATES are deliberately separate (different class
// and token vocabularies), and only @shared lib logic crosses. unknown_columns MUST
// surface - the server counts keys it dropped rather than rendering them, and a
// count nobody sees makes a silent drop silent again.
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
	<div class="jv-pc">
		<template v-if="card.kind === 'create'">
			<div class="jv-pc-head">Create {{ card.doctype }}<template v-if="card.name"> · {{ card.name }}</template></div>
			<div v-for="(r, i) in card.rows" :key="i" class="jv-pc-kv"><span>{{ r.label }}</span><b>{{ r.value }}</b></div>
			<div v-if="!card.rows.length && !(card.tables || []).length" class="jv-pc-empty">No fields set.</div>
			<div v-for="(t, ti) in (card.tables || [])" :key="'t' + ti" class="jv-pc-table">
				<div class="jv-pc-table-head">{{ t.label }} · {{ t.count }} row<template v-if="t.count !== 1">s</template></div>
				<div class="jv-pc-table-scroll">
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
				<div v-if="tableNote(t)" class="jv-pc-more">{{ tableNote(t) }}</div>
			</div>
		</template>

		<template v-else-if="card.kind === 'update'">
			<div class="jv-pc-head">Update {{ card.doctype }}<template v-if="card.name"> · {{ card.name }}</template><template v-if="card.title"> · {{ card.title }}</template></div>
			<div v-for="(d, i) in card.diff" :key="i" class="jv-pc-diff">
				<span class="jv-pc-lbl">{{ d.label }}</span>
				<span class="jv-pc-from">{{ d.from || "(empty)" }}</span>
				<span class="jv-pc-arrow">→</span>
				<span class="jv-pc-to">{{ d.to || "(empty)" }}</span>
			</div>
			<div v-if="!card.diff.length" class="jv-pc-empty">No field changes.</div>
		</template>

		<!-- ORDER IS LOAD-BEARING: records div -> targets <ul v-else-if> -> +N more.
		     v-else-if chains to the immediately preceding sibling carrying a v-if, so
		     putting the +N more div between them would chain the <ul> to IT - and with
		     extra === 0 (always, via the F16 batch cap) every bulk card would render
		     its targets twice, once as records and once as the old list. -->
		<template v-else-if="card.kind === 'verb'">
			<div class="jv-pc-verb">{{ sentence }}</div>
			<div v-if="(card.records || []).length" class="jv-pc-recs">
				<template v-for="(r, i) in card.records" :key="'vr' + i">
					<details v-if="r.rows.length" class="jv-pc-rec" :open="i === 0">
						<summary>
							<span class="jv-pc-chev" aria-hidden="true"></span>
							<span class="jv-pc-rid">{{ r.name }}</span>
							<span v-if="r.title" class="jv-pc-rtitle">{{ r.title }}</span>
						</summary>
						<div class="jv-pc-rbody">
							<div v-for="(f, j) in r.rows" :key="'vf' + j" class="jv-pc-kv"><span>{{ f.label }}</span><b>{{ f.value }}</b></div>
						</div>
					</details>
					<div v-else class="jv-pc-rec jv-pc-rec-bare">
						<span class="jv-pc-rid">{{ r.name }}</span>
						<span v-if="r.title" class="jv-pc-rtitle">{{ r.title }}</span>
					</div>
				</template>
			</div>
			<ul v-else-if="card.count > 1 && card.targets.length" class="jv-pc-list">
				<li v-for="(t, i) in card.targets" :key="i">{{ t }}</li>
				<li v-if="card.extra > 0" class="jv-pc-more">+{{ card.extra }} more</li>
			</ul>
			<div v-if="(card.records || []).length && card.extra > 0" class="jv-pc-more">+{{ card.extra }} more</div>
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

		<template v-else-if="card.kind === 'bulk_update'">
			<div class="jv-pc-head">Update {{ card.count }} {{ card.doctype }} record<template v-if="card.count !== 1">s</template><span v-if="card.varying" class="jv-pc-sub"> · varying changes</span></div>
			<p class="jv-pc-cap">Tap a record to review its changes.</p>
			<div class="jv-pc-recs">
				<details v-for="(r, i) in card.records" :key="i" class="jv-pc-rec" :open="i === 0">
					<summary>
						<span class="jv-pc-chev" aria-hidden="true"></span>
						<span class="jv-pc-rid">{{ r.name }}</span>
						<span v-if="r.title" class="jv-pc-rtitle">{{ r.title }}</span>
						<span v-if="r.fields?.length" class="jv-pc-rfields">{{ r.fields.join(" · ") }}</span>
					</summary>
					<div class="jv-pc-rbody">
						<div v-for="(d, j) in r.diff" :key="j" class="jv-pc-diff">
							<span class="jv-pc-lbl">{{ d.label }}</span>
							<span class="jv-pc-from">{{ d.from || "(empty)" }}</span>
							<span class="jv-pc-arrow">→</span>
							<span class="jv-pc-to">{{ d.to || "(empty)" }}</span>
						</div>
						<div v-if="!r.diff.length" class="jv-pc-empty">No field changes.</div>
					</div>
				</details>
			</div>
			<div v-if="card.extra > 0" class="jv-pc-more">+{{ card.extra }} more · full list in Details</div>
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
/* create: a proposed child table, scrolling inside its own box so the card never
   scrolls the page sideways */
.jv-pc-table { margin-top: 10px; }
.jv-pc-table-head { font-size: 12px; color: var(--ink5); margin-bottom: 4px; }
.jv-pc-table-scroll { overflow-x: auto; max-height: 240px; overflow-y: auto; -webkit-overflow-scrolling: touch; overscroll-behavior: contain; }
.jv-pc-table table { border-collapse: collapse; width: 100%; font-size: 12px; }
.jv-pc-table th, .jv-pc-table td { text-align: left; padding: 4px 8px; white-space: nowrap; }
.jv-pc-table th { color: var(--ink5); font-weight: 500; }
.jv-pc-table td { color: var(--ink8); font-variant-numeric: tabular-nums; }
/* scoped: .jv-pc-more is shared with the verb/batch_create <li>s */
.jv-pc-table .jv-pc-more { font-size: 12px; margin-top: 4px; }
/* bulk update: collapsible per-record from→to list (touch-first) */
.jv-pc-sub { font-weight: 400; color: var(--ink5); }
.jv-pc-cap { font-size: 12px; color: var(--ink5); margin: 0 0 8px; }
.jv-pc-recs { display: flex; flex-direction: column; max-height: 320px; overflow-y: auto; overscroll-behavior: contain; -webkit-overflow-scrolling: touch; }
.jv-pc-rec { border-top: 1px solid var(--border); }
.jv-pc-rec:first-child { border-top: 0; }
.jv-pc-rec > summary { list-style: none; cursor: pointer; display: flex; align-items: center; gap: 10px; min-height: 44px; padding: 8px 2px; user-select: none; -webkit-tap-highlight-color: transparent; }
.jv-pc-rec > summary::-webkit-details-marker { display: none; }
.jv-pc-rec > summary::marker { content: ""; }
.jv-pc-rec > summary:active { background: var(--card2); }
.jv-pc-chev { flex: none; width: 8px; height: 8px; border-right: 1.7px solid var(--ink5); border-bottom: 1.7px solid var(--ink5); transform: rotate(-45deg); transition: transform .15s ease; margin-left: 2px; }
.jv-pc-rec[open] > summary .jv-pc-chev { transform: rotate(45deg); }
/* verb: a name-only record (missing or unreadable) gets no expander, so it needs
   the <summary> row's touch metrics by hand to line up with its expandable siblings. */
.jv-pc-rec-bare { display: flex; align-items: center; gap: 10px; min-height: 44px; padding: 8px 2px 8px 20px; }
.jv-pc-rid { font-family: ui-monospace, Menlo, monospace; font-size: 12px; color: var(--ink9); font-weight: 500; flex: none; }
.jv-pc-rtitle { font-size: 12px; color: var(--ink7); overflow-wrap: anywhere; }
.jv-pc-rfields { font-size: 12px; color: var(--ink5); margin-left: auto; text-align: right; overflow-wrap: anywhere; }
.jv-pc-rbody { padding: 2px 2px 10px 20px; }
@media (max-width: 460px) {
	.jv-pc-rbody .jv-pc-diff { grid-template-columns: 1fr auto 1fr; }
	.jv-pc-rbody .jv-pc-lbl { grid-column: 1 / -1; }
}
@media (prefers-reduced-motion: reduce) { .jv-pc-chev { transition: none; } }
.jv-pc-note { margin-top: 6px; color: var(--ink5); font-size: 12.5px; }
.jv-pc-body { margin: 8px 0 0; padding: 10px; border-radius: 8px; background: var(--card2); color: var(--ink7); font-size: 12.5px; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 220px; overflow-y: auto; }
.jv-pc-details { margin-top: 10px; }
.jv-pc-details summary { cursor: pointer; color: var(--ink5); font-size: 12px; }
.jv-pc-details pre { margin: 6px 0 0; padding: 10px; border-radius: 8px; background: var(--card2); font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow-y: auto; }
</style>
