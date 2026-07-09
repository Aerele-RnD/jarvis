<template>
	<!-- Intro product tour (onboarding step 1, chromeless: no step rail).
		 6 slides in SIDEBAR ORDER: Welcome, Chat, Skills, Macros, File Box,
		 Agents. Translated from the approved preview
		 (docs/superpowers/specs/onboarding-preview-v6.html); self-contained,
		 only depends on the app palette vars OnboardingView already applies. -->
	<div class="tour">
		<div class="tour-stage">

			<!-- slide 1 · welcome -->
			<div v-if="cur === 0" class="slide">
				<div class="slide-copy">
					<span class="eyebrow">✦ Welcome</span>
					<h2>Harness AI agents inside your ERPNext.</h2>
					<p>Jarvis is an AI teammate that lives in your ERP. Ask a question, hand off a task, or let it watch the books, all in plain language.</p>
					<ul class="pts">
						<li><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>Reads your real data, trusting the ledger over guesses</li>
						<li><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>Builds a personalized knowledge base of your business as you work</li>
						<li><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>Respects each user’s Frappe permissions, so everyone sees only what they’re allowed to</li>
						<li><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>Asks before it changes anything</li>
					</ul>
				</div>
				<div class="mock">
					<div class="mock-bar"><i></i><i></i><i></i><span>Jarvis · New chat</span></div>
					<div class="mock-body">
						<div class="m-side" v-html="sideHtml('Chat')"></div>
						<div class="m-main">
							<div class="m-welcome">
								<div class="m-welcome-mk"><svg width="15" height="15" viewBox="0 0 24 24" fill="var(--surface)"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg></div>
								<div class="m-welcome-hi">Good morning, Priya</div>
								<div class="m-welcome-sub">Ask about your ERP data, run a workflow, or draft something.</div>
							</div>
							<div class="m-sugg-grid">
								<div class="m-sugg"><b style="color:#6e8bff">📈</b><div><i>Analyse data</i><u>Which sales orders are overdue?</u></div></div>
								<div class="m-sugg"><b style="color:var(--green)">＋</b><div><i>Take an action</i><u>Create a new Sales Order</u></div></div>
								<div class="m-sugg"><b style="color:var(--amber)">🔍</b><div><i>Search records</i><u>Find a customer or contact</u></div></div>
								<div class="m-sugg"><b style="color:#8b5cf6">✎</b><div><i>Draft content</i><u>Follow-up email to a lead</u></div></div>
							</div>
							<div class="composer">Ask Jarvis…  @ to mention a user, / for a doctype or tool</div>
						</div>
					</div>
				</div>
			</div>

			<!-- slide 2 · chat -->
			<div v-else-if="cur === 1" class="slide">
				<div class="slide-copy">
					<span class="eyebrow">Chat</span>
					<h2>Ask anything about your business.</h2>
					<p>“Which sales orders are overdue?” “Draft a follow-up to this lead.” Jarvis pulls the answer straight from ERPNext and shows its work.</p>
				</div>
				<div class="mock">
					<div class="mock-bar"><i></i><i></i><i></i><span>Chat · Overdue orders</span></div>
					<div class="mock-body">
						<div class="m-side" v-html="sideHtml('Chat')"></div>
						<div class="m-main">
							<div class="cb u">Which sales orders are overdue this month?</div>
							<div class="cb tool"><span class="g"></span>run_report · Sales Order</div>
							<div class="cb a">7 orders are overdue, totalling ₹4.2L. The largest is SO-0142 (Acme, ₹1.1L, 9 days late).</div>
							<div class="composer">Ask a follow-up…</div>
						</div>
					</div>
				</div>
			</div>

			<!-- slide 3 · skills -->
			<div v-else-if="cur === 2" class="slide">
				<div class="slide-copy">
					<span class="eyebrow">Skills</span>
					<h2>It already knows Frappe &amp; ERPNext.</h2>
					<p>Jarvis ships with deep skills for every core doctype, and you can create custom skills for your domain-specific workflows, so it works the way your team already does.</p>
				</div>
				<div class="mock">
					<div class="mock-bar"><i></i><i></i><i></i><span>Skills</span></div>
					<div class="mock-body">
						<div class="m-side" v-html="sideHtml('Skills')"></div>
						<div class="m-main">
							<div class="m-row"><span class="pill">core</span><div class="t">Customer ledger lookup</div><div class="meta"></div></div>
							<div class="m-row"><span class="pill">sales</span><div class="t">Sales order follow-up</div><div class="meta"></div></div>
							<div class="m-row"><span class="pill amber">custom</span><div class="t">Invoice data entry</div><div class="meta"></div></div>
							<div class="m-row"><span class="pill amber">custom</span><div class="t">GST reconciliation</div><div class="meta"></div></div>
							<div class="m-row m-row-dashed"><span class="m-row-cta">＋ New skill</span></div>
						</div>
					</div>
				</div>
			</div>

			<!-- slide 4 · macros -->
			<div v-else-if="cur === 3" class="slide">
				<div class="slide-copy">
					<span class="eyebrow">Macros</span>
					<h2>Turn a routine into one click.</h2>
					<p>Save any multi-step job like “month-end close” or “daily AR reminders” as a macro. Run it on demand or on a schedule, and watch every run.</p>
				</div>
				<div class="mock">
					<div class="mock-bar"><i></i><i></i><i></i><span>Macros · Runs</span></div>
					<div class="mock-body">
						<div class="m-side" v-html="sideHtml('Macros')"></div>
						<div class="m-main">
							<div class="m-row"><span class="pill amber">running</span><div class="t">Month-end close</div><div class="meta"></div></div>
							<div class="m-row"><span class="pill">done</span><div class="t">Daily AR reminders</div><div class="meta"></div></div>
							<div class="m-row"><span class="pill">done</span><div class="t">Sync price list</div><div class="meta"></div></div>
							<div class="m-row"><span class="pill">done</span><div class="t">Weekly sales digest</div><div class="meta"></div></div>
						</div>
					</div>
				</div>
			</div>

			<!-- slide 5 · file box -->
			<div v-else-if="cur === 4" class="slide">
				<div class="slide-copy">
					<span class="eyebrow">File Box</span>
					<h2>Drop files in, get clean entries out.</h2>
					<p>Upload invoices, bank statements or price lists. Jarvis reads them, extracts the details, and drafts the entries in ERPNext. You just review and approve.</p>
				</div>
				<div class="mock">
					<div class="mock-bar"><i></i><i></i><i></i><span>File Box</span></div>
					<div class="mock-body">
						<div class="m-side" v-html="sideHtml('File Box')"></div>
						<div class="m-main">
							<div class="m-row"><span class="pill amber">reading</span><span class="fname">INV-ACME-0921.pdf</span><div class="meta"></div></div>
							<div class="m-row"><span class="pill">extracted</span><span class="fname">bank-stmt-jun.pdf</span><div class="meta"></div></div>
							<div class="m-row"><span class="pill">filed</span><span class="fname">price-list-q3.xlsx</span><div class="meta"></div></div>
							<div class="m-row m-row-dashed"><span class="m-row-cta">⇪ Drop a file or browse</span></div>
						</div>
					</div>
				</div>
			</div>

			<!-- slide 6 · agents (final: single in-copy CTA, footer Next/Skip hidden) -->
			<div v-else class="slide">
				<div class="slide-copy">
					<span class="eyebrow">Agents</span>
					<h2>Put specialists to work in the background.</h2>
					<p>Install expert-built ERPNext agents, or build your own custom agents for your team’s workflows. They watch and surface findings before you ask.</p>
					<p class="final-call"><mark>Ready to see it on your data? Onboard Jarvis and explore everything hands-on. It takes about two minutes.</mark></p>
					<div class="final-cta">
						<button class="btn btn--primary btn--lg" @click="$emit('finish')">Onboard Jarvis →</button>
					</div>
				</div>
				<div class="mock">
					<div class="mock-bar"><i></i><i></i><i></i><span>Agents</span></div>
					<div class="mock-body">
						<div class="m-side" v-html="sideHtml('Agents')"></div>
						<div class="m-main">
							<div class="m-grid">
								<div class="m-card"><div class="ico">🔎</div><div class="nm">Ledger Scrutiny</div><div class="ds">Analytical review &amp; audit checks on your books</div><span class="m-inst on">Installed</span></div>
								<div class="m-card"><div class="ico">💰</div><div class="nm">AR Follow-up</div><div class="ds">Chases overdue receivables, drafts reminders</div><span class="m-inst">Install</span></div>
								<div class="m-card"><div class="ico">📅</div><div class="nm">Month-end Close</div><div class="ds">Runs your closing checklist on schedule</div><span class="m-inst">Install</span></div>
								<div class="m-card dashed"><div class="ico ico-plain">＋</div><div class="nm">Build custom</div><div class="ds">An agent for your own workflow</div></div>
							</div>
						</div>
					</div>
				</div>
			</div>

		</div>

		<div class="tour-foot">
			<div class="dots">
				<button v-for="i in SLIDE_COUNT" :key="i" :class="{ on: cur === i - 1 }"
						:aria-label="`Go to slide ${i}`" :aria-current="cur === i - 1 ? 'step' : undefined"
						@click="go(i - 1)"></button>
			</div>
			<div class="tour-nav">
				<button v-if="!isLast" class="skip" @click="$emit('skip')">Skip tour</button>
				<button class="btn btn--ghost btn--sm" :style="{ visibility: cur === 0 ? 'hidden' : 'visible' }" @click="step(-1)">Back</button>
				<button v-if="!isLast" class="btn btn--primary btn--sm" @click="step(1)">Next</button>
			</div>
		</div>
	</div>
</template>

<script setup>
import { ref, computed } from "vue"

// 'finish' = the final-slide CTA (or advancing past the last slide);
// 'skip' = the footer "Skip tour" link. Both land the wizard on the Plan step.
const emit = defineEmits(["finish", "skip"])

const SLIDE_COUNT = 6
const LAST = SLIDE_COUNT - 1
const cur = ref(0)
const isLast = computed(() => cur.value === LAST)

function go(i) {
	cur.value = Math.max(0, Math.min(LAST, i))
}
function step(d) {
	if (cur.value === LAST && d > 0) {
		emit("finish")
		return
	}
	go(cur.value + d)
}

// ---- mock sidebar: mirrors the REAL app sidebar (brand + user, New Chat,
// Search Chat, feather-icon nav, Recent chats), rendered from data exactly
// like the preview's NAV_ICONS renderer. Static trusted strings only.
const FI = (d, size = 11) =>
	`<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`
const NAV_ICONS = {
	"Chat": '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
	"Skills": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
	"Macros": '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
	"File Box": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
	"Agents": '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/>',
}
const NAV_ORDER = ["Chat", "Skills", "Macros", "File Box", "Agents"]

function sideHtml(active) {
	return (
		'<div class="m-brand"><span class="d"><svg width="10" height="10" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z"/></svg></span><span class="col"><b>Jarvis</b><small>Administrator</small></span></div>' +
		`<div class="m-act">${FI('<path d="M12 5v14M5 12h14"/>')}New Chat</div>` +
		`<div class="m-act">${FI('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>')}Search Chat</div>` +
		NAV_ORDER.map((n) => `<div class="m-nav${n === active ? " on" : ""}">${FI(NAV_ICONS[n])}${n}</div>`).join("") +
		'<div class="m-recent">Recent chats</div>' +
		'<div class="m-recent-item">Overdue sales orders</div>'
	)
}
</script>

<style scoped>
/* Tour panel height is standardized with the wizard steps (tour = the tallest,
   ~624px) so the dialog never jumps between steps; relaxed on mobile. */
.tour {
	position: relative;
	min-height: 624px;
	display: grid;
	grid-template-rows: 1fr auto;
	font-family: 'Inter', system-ui, sans-serif;
	color: var(--text);
}
.tour-stage { position: relative; overflow: hidden; display: flex; flex-direction: column; }
.slide {
	flex: 1;
	display: grid;
	padding: 40px 44px 8px;
	grid-template-columns: 1fr 1.15fr;
	gap: 36px;
	align-items: center;
	min-height: 472px;
	animation: jvTourFade .3s ease;
}
@keyframes jvTourFade {
	from { opacity: 0; transform: translateY(6px); }
	to { opacity: 1; transform: none; }
}
@media (prefers-reduced-motion: reduce) {
	.slide { animation: none; }
	.dots button { transition: none; }
	.btn { transition: none; }
}

/* keyboard focus */
button:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }

/* ---- copy column ---- */
.slide-copy .eyebrow {
	display: inline-flex; align-items: center; gap: 7px;
	font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
	color: var(--blue); background: var(--blue-bg); border: 1px solid var(--blue-bd);
	border-radius: 99px; padding: 4px 11px; margin-bottom: 16px;
}
.slide-copy h2 { font-size: 30px; font-weight: 680; line-height: 1.12; letter-spacing: -.02em; margin: 0 0 12px; text-wrap: balance; }
.slide-copy p { font-size: 15px; line-height: 1.55; color: var(--text-2); margin: 0; max-width: 42ch; }
.slide-copy .pts { list-style: none; margin: 18px 0 0; padding: 0; display: grid; gap: 9px; }
.slide-copy .pts li { display: flex; gap: 9px; align-items: flex-start; font-size: 13.5px; color: var(--text-2); }
.slide-copy .pts svg { color: #6e8bff; flex: none; margin-top: 1px; }
/* highlighted closing invitation on the final slide */
.final-call { margin-top: 18px !important; font-size: 14.5px !important; line-height: 1.7 !important; }
.final-call mark {
	background: linear-gradient(120deg, var(--blue-bg), color-mix(in srgb, #8b5cf6 14%, var(--blue-bg)));
	color: var(--text); padding: 3px 7px; border-radius: 6px;
	-webkit-box-decoration-break: clone; box-decoration-break: clone; font-weight: 550;
}
.final-cta { margin-top: 16px; }

/* ---- buttons (local to the tour; the wizard steps have their own) ---- */
.btn {
	display: inline-flex; align-items: center; justify-content: center; gap: 7px;
	height: 40px; padding: 0 20px; border-radius: 11px; border: 1px solid transparent;
	font-family: inherit; font-size: 13.5px; font-weight: 600; line-height: 1;
	cursor: pointer; white-space: nowrap;
	transition: transform .12s, box-shadow .15s, background .15s, border-color .15s;
}
.btn:active { transform: scale(.98); }
.btn--primary { background: var(--blue); color: #fff; box-shadow: 0 2px 10px rgba(20, 20, 30, .16); }
.btn--primary:hover { transform: translateY(-1px); box-shadow: 0 8px 22px rgba(20, 20, 30, .22); }
.btn--ghost { background: var(--surface); border-color: var(--border-2); color: var(--text-2); }
.btn--ghost:hover { background: var(--surface-2); color: var(--text); border-color: var(--border); }
.btn--sm { height: 34px; padding: 0 13px; font-size: 12.5px; border-radius: 9px; }
.btn--lg { height: 46px; padding: 0 26px; font-size: 14.5px; border-radius: 12px; }

/* ---- mock "device" framing each product surface ---- */
.mock {
	border: 1px solid var(--border); border-radius: 14px; background: var(--surface-1);
	overflow: hidden; box-shadow: 0 18px 50px rgba(20, 20, 30, .14); aspect-ratio: 16/11;
}
.mock-bar { display: flex; align-items: center; gap: 6px; padding: 9px 12px; border-bottom: 1px solid var(--border); background: var(--surface); }
.mock-bar i { width: 9px; height: 9px; border-radius: 50%; background: var(--border-2); }
.mock-bar span { margin-left: 8px; font-size: 11px; color: var(--text-3); }
.mock-body { display: flex; height: calc(100% - 39px); }
.m-main { flex: 1; padding: 14px; overflow: hidden; position: relative; }

/* the sidebar itself is injected via v-html → style through :deep() */
.m-side {
	width: 34%; max-width: 150px; background: var(--surface-1); border-right: 1px solid var(--border);
	padding: 9px 8px; display: flex; flex-direction: column; gap: 2px; overflow: hidden;
}
.m-side :deep(.m-brand) { display: flex; align-items: center; gap: 7px; padding: 2px 6px 8px; }
.m-side :deep(.m-brand .d) { width: 18px; height: 18px; border-radius: 5px; background: linear-gradient(135deg, #6e8bff, #8b5cf6); display: grid; place-items: center; flex: none; }
.m-side :deep(.m-brand .col) { display: flex; flex-direction: column; line-height: 1.15; min-width: 0; }
.m-side :deep(.m-brand b) { font-size: 10.5px; }
.m-side :deep(.m-brand small) { font-size: 8px; color: var(--text-3); }
.m-side :deep(.m-act) { display: flex; align-items: center; gap: 7px; padding: 4px 7px; font-size: 10px; color: var(--text-2); white-space: nowrap; }
.m-side :deep(.m-act svg) { flex: none; color: var(--text-3); }
.m-side :deep(.m-nav) { display: flex; align-items: center; gap: 7px; padding: 4.5px 7px; border-radius: 6px; font-size: 10.5px; color: var(--text-2); white-space: nowrap; }
.m-side :deep(.m-nav.on) { background: var(--surface-3); color: var(--text); font-weight: 600; }
.m-side :deep(.m-nav svg) { flex: none; color: var(--text-3); }
.m-side :deep(.m-nav.on svg) { color: var(--text); }
.m-side :deep(.m-recent) { font-size: 8px; color: var(--text-3); padding: 7px 7px 0; }
.m-side :deep(.m-recent-item) { font-size: 9.5px; color: var(--text-2); padding: 4px 7px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* ---- welcome mock ---- */
.m-welcome { text-align: center; padding-top: 10px; }
.m-welcome-mk { width: 30px; height: 30px; border-radius: 8px; background: var(--text); display: grid; place-items: center; margin: 0 auto 8px; }
.m-welcome-hi { font-size: 12.5px; font-weight: 650; margin-bottom: 3px; }
.m-welcome-sub { font-size: 9.5px; color: var(--text-3); }
.m-sugg-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; margin: 12px auto 0; max-width: 290px; }
.m-sugg { display: flex; gap: 8px; align-items: flex-start; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); padding: 8px 9px; }
.m-sugg b { font-size: 11px; font-style: normal; flex: none; line-height: 1.3; }
.m-sugg i { display: block; font-size: 9.5px; font-weight: 600; font-style: normal; color: var(--text); margin-bottom: 2px; }
.m-sugg u { display: block; font-size: 8.5px; color: var(--text-3); text-decoration: none; line-height: 1.3; }

/* ---- chat mock ---- */
.cb { max-width: 74%; padding: 8px 11px; border-radius: 12px; font-size: 11.5px; line-height: 1.4; margin-bottom: 9px; }
.cb.u { margin-left: auto; background: var(--blue); color: #fff; border-bottom-right-radius: 4px; }
.cb.a { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border); border-bottom-left-radius: 4px; }
.cb.tool {
	display: inline-flex; align-items: center; gap: 6px; font-size: 10.5px; color: var(--text-3);
	background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 4px 9px; margin-bottom: 9px; max-width: none;
}
.cb.tool .g { width: 6px; height: 6px; border-radius: 50%; background: var(--green); }
.composer {
	position: absolute; left: 14px; right: 14px; bottom: 12px; height: 30px;
	border: 1px solid var(--border-2); border-radius: 9px; background: var(--surface);
	display: flex; align-items: center; padding: 0 10px; font-size: 10px; color: var(--text-3);
	white-space: nowrap; overflow: hidden;
}

/* ---- rows mock (skills / macros / file box) ---- */
.m-row { display: flex; align-items: center; gap: 9px; padding: 8px 9px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); margin-bottom: 7px; }
.m-row .pill { font-size: 9px; font-weight: 600; padding: 2px 7px; border-radius: 99px; background: var(--green-bg); color: var(--green); border: 1px solid var(--green-bd); flex: none; }
.m-row .pill.amber { background: var(--amber-bg); color: var(--amber); border-color: var(--amber-bd); }
.m-row .t { flex: 1; min-width: 0; font-size: 10px; font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.m-row .fname { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 9.5px; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.m-row .meta { margin-left: auto; height: 6px; width: 52px; border-radius: 4px; background: var(--surface-2); flex: none; }
.m-row-dashed { border-style: dashed; justify-content: center; }
.m-row-cta { font-size: 10px; font-weight: 600; color: var(--text-2); }

/* ---- agents mock ---- */
.m-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.m-card { border: 1px solid var(--border); border-radius: 9px; background: var(--surface); padding: 10px; }
.m-card .ico { width: 22px; height: 22px; border-radius: 7px; background: var(--blue-bg); border: 1px solid var(--blue-bd); margin-bottom: 7px; display: grid; place-items: center; font-size: 11px; }
.m-card .ico-plain { background: var(--surface-2); border-color: var(--border); }
.m-card .nm { font-size: 10.5px; font-weight: 600; color: var(--text); margin-bottom: 2px; }
.m-card .ds { font-size: 8.5px; color: var(--text-3); line-height: 1.35; }
.m-card.dashed { border-style: dashed; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 4px; }
.m-inst { display: inline-block; margin-top: 8px; font-size: 9px; font-weight: 600; padding: 3px 8px; border-radius: 6px; background: var(--text); color: var(--surface); }
.m-inst.on { background: var(--green-bg); color: var(--green); border: 1px solid var(--green-bd); }

/* ---- footer: dots + nav ---- */
.tour-foot { display: flex; align-items: center; justify-content: space-between; padding: 16px 44px 26px; border-top: 1px solid var(--border); background: var(--surface); }
.dots { display: flex; gap: 7px; }
.dots button { width: 8px; height: 8px; border-radius: 99px; border: none; background: var(--border-2); cursor: pointer; padding: 0; transition: width .2s, background .2s; }
.dots button.on { width: 22px; background: var(--blue); }
.tour-nav { display: flex; gap: 10px; align-items: center; }
.skip { font-size: 12.5px; color: var(--text-3); background: none; border: none; cursor: pointer; font-family: inherit; }
.skip:hover { color: var(--text-2); }

@media (max-width: 820px) {
	.tour { min-height: 0; }
	.slide { grid-template-columns: 1fr; gap: 20px; padding: 26px 24px 4px; min-height: 0; }
	.slide-copy { order: 2; }
	.mock { order: 1; }
	.tour-foot { padding: 14px 22px 20px; }
}
</style>
