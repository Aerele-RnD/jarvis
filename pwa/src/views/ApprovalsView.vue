<script setup>
import { onMounted, ref } from "vue"
import { useRouter } from "vue-router"
import { renderMarkdown } from "@shared/markdown.js"
import * as api from "../api"
import { store } from "../store"
import { relativeTime } from "../lib/time"

// The approval queue: the agent stopped and asked a human a question. It lives
// on the phone precisely because the person who can answer is usually not at a
// desk — that is the whole reason the queue exists.
const router = useRouter()

const rows = ref([])
const loaded = ref(false)
const openRow = ref(null)
const answer = ref("")
const busy = ref("")
const error = ref("")

async function load() {
	try {
		const r = await api.listApprovals("Pending", 50)
		rows.value = Array.isArray(r) ? r : []
	} catch (e) {
		error.value = e?.message || "Couldn't load approvals."
	} finally {
		loaded.value = true
		store.loadPendingCount()
	}
}

async function decide(row, decision, approve) {
	const text = (decision || "").trim()
	if (!text) return
	busy.value = row.name
	error.value = ""
	try {
		await api.decideApproval(row.name, text, approve)
		// The decision resumes the agent in the chat it came from, so leave the
		// board and go watch it happen.
		rows.value = rows.value.filter((r) => r.name !== row.name)
		openRow.value = null
		answer.value = ""
		store.loadPendingCount()
		if (row.conversation) router.push(`/c/${row.conversation}`)
	} catch (e) {
		error.value = e?.message || "Couldn't record that decision."
	} finally {
		busy.value = ""
	}
}

function toggle(row) {
	openRow.value = openRow.value === row.name ? null : row.name
	answer.value = ""
	error.value = ""
}

onMounted(load)
</script>

<template>
	<div class="jv-bar">
		<button class="jv-icon-btn" aria-label="Back" @click="router.push('/')">
			<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
				<path d="m15 18-6-6 6-6" />
			</svg>
		</button>
		<div class="jv-title">Approvals</div>
	</div>

	<div class="jv-scroll">
		<div v-if="!loaded" class="jv-empty">Loading…</div>

		<div v-else-if="!rows.length" class="jv-empty">
			<div style="font-size: 15px; font-weight: 600; color: var(--ink9)">Nothing to approve</div>
			<div style="font-size: 14px; line-height: 1.5">
				When Jarvis needs a decision before it acts, it lands here.
			</div>
		</div>

		<ul v-else class="jv-alist">
			<li v-for="r in rows" :key="r.name" class="jv-acard">
				<button class="jv-ahead" @click="toggle(r)">
					<div class="jv-amain">
						<div class="jv-atitle">{{ r.title || r.question || "Jarvis needs a decision" }}</div>
						<div class="jv-ameta">
							<span v-if="r.document_type" class="jv-atag">{{ r.document_type }}</span>
							{{ relativeTime(r.creation) }}
						</div>
					</div>
					<svg class="jv-achev" :class="{ 'is-open': openRow === r.name }" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<path d="m6 9 6 6 6-6" />
					</svg>
				</button>

				<div v-if="openRow === r.name" class="jv-abody">
					<div v-if="r.question" class="jv-aquestion">{{ r.question }}</div>
					<div v-if="r.context_md" class="jv-md" v-html="renderMarkdown(r.context_md)" />

					<!-- The agent may offer named options; otherwise the human types a
					     free-text answer. Either way the reply goes back as a normal
					     chat turn, so the agent sees it exactly like any message. -->
					<div v-if="r.options?.length" class="jv-aoptions">
						<button
							v-for="o in r.options"
							:key="o"
							class="jv-aoption"
							:disabled="busy === r.name"
							@click="decide(r, o, true)"
						>
							{{ o }}
						</button>
					</div>

					<template v-else>
						<textarea v-model="answer" class="jv-atext" rows="2" placeholder="Your answer…" />
						<div class="jv-aactions">
							<button class="jv-btn is-ghost" :disabled="busy === r.name" @click="decide(r, answer || 'Rejected', false)">
								Reject
							</button>
							<button class="jv-btn is-primary" :disabled="busy === r.name || !answer.trim()" @click="decide(r, answer, true)">
								Approve
							</button>
						</div>
					</template>

					<div v-if="error && busy !== r.name" class="jv-aerror">{{ error }}</div>
				</div>
			</li>
		</ul>
	</div>
</template>

<style scoped>
.jv-alist {
	list-style: none;
	margin: 0;
	padding: 8px;
	display: flex;
	flex-direction: column;
	gap: 8px;
}
.jv-acard {
	border: 1px solid var(--border);
	border-radius: 12px;
	background: var(--card);
	overflow: hidden;
}
.jv-ahead {
	display: flex;
	align-items: center;
	gap: 10px;
	width: 100%;
	padding: 13px 12px;
	border: 0;
	background: transparent;
	font: inherit;
	text-align: left;
	cursor: pointer;
}
.jv-amain {
	flex: 1;
	min-width: 0;
}
.jv-atitle {
	font-size: 14px;
	font-weight: 600;
	color: var(--ink9);
	line-height: 1.35;
}
.jv-ameta {
	display: flex;
	align-items: center;
	gap: 6px;
	margin-top: 4px;
	font-size: 11.5px;
	color: var(--ink5);
}
.jv-atag {
	padding: 2px 6px;
	border-radius: 5px;
	background: var(--card2);
	color: var(--ink6);
	font-weight: 500;
}
.jv-achev {
	flex: none;
	color: var(--ink4);
	transition: transform 0.15s ease;
}
.jv-achev.is-open {
	transform: rotate(180deg);
}
.jv-abody {
	padding: 0 12px 12px;
	border-top: 1px solid var(--border);
	padding-top: 12px;
}
.jv-aquestion {
	font-size: 13.5px;
	line-height: 1.5;
	color: var(--ink8);
}
.jv-md {
	margin-top: 8px;
	font-size: 13px;
	line-height: 1.55;
	color: var(--ink6);
}
.jv-md :deep(pre) {
	display: block;
	max-width: 100%;
	overflow-x: auto;
	padding: 10px;
	border-radius: 8px;
	background: var(--card2);
	font-size: 12px;
}
.jv-aoptions {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	margin-top: 12px;
}
.jv-aoption {
	padding: 10px 14px;
	border: 1px solid var(--border2);
	border-radius: 10px;
	background: var(--card);
	color: var(--ink8);
	font: inherit;
	font-size: 14px;
	font-weight: 500;
	cursor: pointer;
}
.jv-aoption:active {
	background: var(--accent-bg);
	border-color: transparent;
	color: var(--accent);
}
.jv-atext {
	width: 100%;
	margin-top: 12px;
	padding: 10px 12px;
	border: 1px solid var(--border2);
	border-radius: 10px;
	background: var(--card);
	color: var(--ink9);
	font: inherit;
	font-size: 14px;
	line-height: 1.4;
	resize: none;
	outline: none;
}
.jv-atext:focus {
	border-color: var(--accent);
}
.jv-aactions {
	display: flex;
	gap: 8px;
	margin-top: 10px;
}
.jv-btn {
	flex: 1;
	height: 44px;
	border: 0;
	border-radius: 10px;
	font: inherit;
	font-size: 14.5px;
	font-weight: 600;
	cursor: pointer;
}
.jv-btn.is-primary {
	background: var(--accent-solid);
	color: #fff;
}
.jv-btn.is-ghost {
	border: 1px solid var(--border2);
	background: var(--card);
	color: var(--ink8);
}
.jv-btn:disabled {
	opacity: 0.55;
}
.jv-aerror {
	margin-top: 10px;
	font-size: 12.5px;
	color: var(--red);
}
</style>
