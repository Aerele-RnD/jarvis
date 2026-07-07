<template>
	<div class="jv-ob-root" :class="{ 'jv-dark': dark }" :style="paletteVars">

		<!-- Framing orbs: two quiet deep-blue orbs settle into the empty corners and
			 frame the wizard without touching it. Decorative only (aria-hidden, no
			 pointer events); deep navy in light for a calm, monochrome-consistent
			 look, brighter on dark so they still read. -->
		<div class="jv-ob-bg" aria-hidden="true">
			<div class="jv-ob-orb jv-ob-orb-tl"></div>
			<div class="jv-ob-orb jv-ob-orb-br"></div>
		</div>

		<!-- Branded header — a centered wizard reads better than a full-height
			 empty sidebar; the logo mark keeps it unmistakably Jarvis. -->
		<header class="jv-ob-header">
			<div class="jv-ob-logo"><svg width="18" height="18" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg></div>
			<span class="jv-ob-brand">Jarvis</span>
			<span class="jv-ob-setup">Set up your workspace</span>
		</header>

		<main class="jv-ob-main">
			<div class="jv-ob-center">
			<div class="jv-ob-wrap">
				<!-- ===== step indicator — managed mode only, mirrors desk renderSteps
					 (jarvis_onboarding.js ~213: STEP_NAMES = Account/Plan/Pay/Connect AI).
					 Hidden on the mode-choice screen and for self-host (single step). ===== -->
				<div v-if="state.mode === 'managed' && state.step !== 'mode'" class="jv-ob-steps">
					<template v-for="(name, i) in STEP_NAMES" :key="name">
						<span class="jv-ob-step" :class="{ done: i + 1 < managedStepNum, active: i + 1 === managedStepNum }">
							<span class="jv-ob-step-dot">{{ i + 1 < managedStepNum ? "✓" : i + 1 }}</span>
							<span class="jv-ob-step-label">{{ name }}</span>
						</span>
						<span v-if="i < STEP_NAMES.length - 1" class="jv-ob-step-line" :class="{ done: i + 1 < managedStepNum }"></span>
					</template>
				</div>

				<!-- ===== step area — placeholder panels; Tasks 3-5 replace these ===== -->
				<div class="jv-ob-body">
					<div v-if="state.step === 'mode'">
						<h1 class="jv-ob-h1">How do you want to run Jarvis?</h1>
						<p class="jv-ob-sub">Choose where the openclaw agent runs. You can switch later from My Account.</p>
						<!-- Ported verbatim from desk renderModeChoice (jarvis_onboarding.js ~262). -->
						<div class="jv-ob-modes">
							<div class="jv-ob-mode">
								<div class="jv-ob-mode-icon">☁</div>
								<div class="jv-ob-mode-name">Managed</div>
								<ul class="jv-ob-mode-feats">
									<li><span class="jv-ob-tick">✓</span>We host the openclaw agent for you</li>
									<li><span class="jv-ob-tick">✓</span>Includes the Jarvis persona + Frappe skills</li>
									<li><span class="jv-ob-tick">✓</span>Managed LLM proxy — pool your API keys &amp; chat subscriptions, with automatic failover</li>
									<li><span class="jv-ob-tick">✓</span>Simple plan &amp; billing</li>
								</ul>
								<button class="jv-ob-btn jv-ob-btn-primary jv-ob-mode-btn" @click="setMode('managed')">Choose →</button>
							</div>
							<div class="jv-ob-mode">
								<div class="jv-ob-mode-icon">🖥</div>
								<div class="jv-ob-mode-name">Self-hosted</div>
								<ul class="jv-ob-mode-feats">
									<li><span class="jv-ob-tick">✓</span>Bring your own openclaw server</li>
									<li><span class="jv-ob-tick">✓</span>Bring your own LLM</li>
									<li><span class="jv-ob-tick">✓</span>Open-source · bring your own persona &amp; skills</li>
									<li class="jv-ob-mode-warn"><span class="jv-ob-warn-icon">⚠</span>Not included: the Jarvis persona + Frappe skill packs, the managed LLM proxy (pooling &amp; failover), and managed updates &amp; support.</li>
								</ul>
								<button class="jv-ob-btn jv-ob-mode-btn" @click="setMode('selfhost')">Choose →</button>
							</div>
						</div>
					</div>

					<!-- ===== Account — ported from desk renderAccount (jarvis_onboarding.js
						 ~378). No Company Link-control (desk falls back to a plain input
						 anyway when make_control throws); validation matches desk verbatim. ===== -->
					<div v-else-if="state.step === 'account'">
						<h1 class="jv-ob-h1">Create your account</h1>
						<p class="jv-ob-sub">We'll set up Jarvis for this site.</p>
						<label class="jv-ob-label" for="jv-ob-email">Work email</label>
						<input id="jv-ob-email" class="jv-ob-input" type="email" v-model="state.email"
							   placeholder="you@company.com" autocomplete="email" required aria-required="true"
							   @keydown.enter="onAccountSubmit">
						<label class="jv-ob-label" for="jv-ob-company">Company</label>
						<input id="jv-ob-company" class="jv-ob-input" type="text" v-model="state.company"
							   placeholder="Acme Inc." autocomplete="organization" list="jv-ob-company-list" required aria-required="true"
							   @keydown.enter="onAccountSubmit">
						<datalist id="jv-ob-company-list">
								<option v-for="c in state.companies" :key="c" :value="c" />
							</datalist>
							<div class="jv-ob-err" role="alert" aria-live="polite">{{ state.accountErr }}</div>
						<div class="jv-ob-placeholder-actions">
							<button class="jv-ob-btn" :disabled="accountBusy" @click="goBack">← Back</button>
							<button class="jv-ob-btn jv-ob-btn-primary" :disabled="accountBusy" @click="onAccountSubmit">
								{{ accountBusy ? "Working…" : "Continue →" }}
							</button>
						</div>
					</div>

					<!-- ===== Plan — ported from desk renderPlan (jarvis_onboarding.js ~481). ===== -->
					<div v-else-if="state.step === 'plan'">
						<h1 class="jv-ob-h1">Choose your plan</h1>
						<p class="jv-ob-sub">Pay as you go — no auto-renewal. Extend anytime.</p>
						<div v-if="state.plansLoading" class="jv-ob-placeholder">Loading plans…</div>
						<div v-else-if="state.plansErr" class="jv-ob-err">{{ state.plansErr }}</div>
						<div v-else-if="!state.plans.length" class="jv-ob-placeholder">No plans are available right now. Please contact support.</div>
						<template v-else>
							<div class="jv-ob-plans">
								<div v-for="p in state.plans" :key="p.name" class="jv-ob-plan"
									 :class="{ selected: state.planName === p.name }" @click="state.planName = p.name">
									<div class="jv-ob-plan-badge">✓</div>
									<div class="jv-ob-plan-name">{{ p.plan_name }}</div>
									<div class="jv-ob-plan-price">{{ planPriceLabel(p.price_inr, p.billing_cycle) }}</div>
									<ul class="jv-ob-plan-feats">
										<li v-for="(f, i) in planFeatures(p)" :key="i"><span class="jv-ob-tick">✓</span>{{ f }}</li>
										<li v-if="!planFeatures(p).length" class="jv-ob-muted">{{ p.billing_cycle }} plan</li>
									</ul>
								</div>
							</div>
							<div class="jv-ob-placeholder-actions">
								<button class="jv-ob-btn" @click="goBack">← Back</button>
								<button class="jv-ob-btn jv-ob-btn-primary" :disabled="!state.planName" @click="onPlanContinue">Continue →</button>
							</div>
						</template>
					</div>

					<!-- ===== Pay — ported from desk renderPay + renderVerifyEmail + startPay/
						 openCheckout/devOnboard (jarvis_onboarding.js ~515, ~1575-1682). The
						 Razorpay options/handler fields below are lifted verbatim; see
						 task-4-report.md for the field-by-field comparison. ===== -->
					<div v-else-if="state.step === 'pay'">
						<template v-if="state.provisioning || state.provisionErr">
								<h1 class="jv-ob-h1">Setting up your workspace</h1>
								<p v-if="state.provisioning" class="jv-ob-sub">Payment received — we're provisioning your Jarvis workspace. This usually takes under a minute…</p>
								<p v-if="state.provisionErr" class="jv-ob-err" role="alert">{{ state.provisionErr }}</p>
								<div v-if="state.provisionErr" class="jv-ob-placeholder-actions">
									<button class="jv-ob-btn jv-ob-btn-primary" @click="proceedAfterPay">Retry</button>
								</div>
							</template>
							<template v-else-if="state.payPhase === 'verify'">
							<h1 class="jv-ob-h1">Check your email</h1>
							<p class="jv-ob-sub">We sent a confirmation link to <b>{{ state.email || "your email" }}</b>.
								Click the link to verify your address, then come back here and click the button below
								to continue to payment.</p>
							<p class="jv-ob-sub">The link expires in 24 hours. Check your spam folder if it doesn't arrive.</p>
							<div class="jv-ob-err">{{ state.payErr }}</div>
							<div class="jv-ob-placeholder-actions">
								<button class="jv-ob-btn jv-ob-btn-primary" :disabled="state.payBusy" @click="onVerifyCheck">
									{{ state.payBusy ? "Working…" : "I've verified my email →" }}
								</button>
							</div>
						</template>
						<template v-else-if="state.successData">
							<h1 class="jv-ob-h1">Payment complete</h1>
							<p class="jv-ob-sub">You're all set — continue to connect your AI.</p>
							<div class="jv-ob-placeholder-actions">
								<button class="jv-ob-btn jv-ob-btn-primary" @click="goNext">Continue →</button>
							</div>
						</template>
						<template v-else>
							<h1 class="jv-ob-h1">Review &amp; {{ state.devActive ? "connect" : "pay" }}</h1>
							<div class="jv-ob-summary">
								<div class="jv-ob-row"><span>Email</span><b>{{ state.email }}</b></div>
								<div class="jv-ob-row"><span>Company</span><b>{{ state.company }}</b></div>
								<div class="jv-ob-row"><span>Plan</span><b>{{ selectedPlan.plan_name || "" }}</b></div>
								<div class="jv-ob-row jv-ob-row-total"><span>Due now</span><b>{{ planPriceLabel(selectedPlan.price_inr, selectedPlan.billing_cycle) }}</b></div>
							</div>
							<div v-if="state.devActive" class="jv-ob-devnote">Developer mode — payment is skipped (dev signup).</div>
							<div class="jv-ob-err">{{ state.payErr }}</div>
							<div class="jv-ob-placeholder-actions">
								<button class="jv-ob-btn" :disabled="state.payBusy" @click="goBack">← Back</button>
								<button class="jv-ob-btn jv-ob-btn-primary" :disabled="state.payBusy" @click="onPayClick">
									{{ state.payBusy ? "Working…" : (state.devActive ? "Dev signup & connect" : "Sign up & pay →") }}
								</button>
							</div>
						</template>
					</div>

					<!-- ===== Connect AI (managed) — embeds the shared LlmPoolEditor component
						 (same one AccountView uses), restricted to :modes="['quick']" so
						 onboarding shows only a single direct model. The Preset/Custom
						 proxy-pool tabs + Direct/Proxy badge are intentionally hidden here to
						 keep signup fast and decision-free; advanced pooling/failover stays
						 available on the Account page. The component owns save_llm_pool.
						 A "Back" button here returns to Pay; that step guards against a
						 second charge by showing a "Payment complete → Continue" state once
						 payment has gone through (state.successData). ===== -->
					<div v-else-if="state.step === 'connect'">
						<h1 class="jv-ob-h1">Connect your AI</h1>
						<p class="jv-ob-sub">Pick which model Jarvis should use. You can change this anytime from My Account.</p>
						<LlmPoolEditor ref="poolRef" :editable="true" :modes="['quick']" :footerless="true" @saved="onConnected" @ready="connectReady = $event" />
						<div v-if="state.finishing" class="jv-ob-note">Finishing setup…</div>
						<div v-else-if="state.finishNote" class="jv-ob-note">
							<span>{{ state.finishNote }}</span>
							<button class="jv-ob-btn jv-ob-btn-primary" @click="forceContinue">Continue to Jarvis →</button>
						</div>
						<div class="jv-ob-placeholder-actions" style="margin-top:18px;">
							<button class="jv-ob-btn" @click="goBack">← Back</button>
							<button v-if="connectReady || savingConnect" class="jv-ob-btn jv-ob-btn-primary" :class="{ 'jv-ob-cta-ready': connectReady && !savingConnect }" :disabled="savingConnect" @click="saveConnect">
								{{ savingConnect ? "Onboarding…" : "Onboard Jarvis" }}
							</button>
						</div>
					</div>

					<!-- ===== Self-host — ported from desk renderSelfHost + renderShResults
						 (jarvis_onboarding.js ~296-376). Field names/args match
						 test_connection / save_self_hosted verbatim (base_url, token, deep,
						 stream) — see api.js's testSelfHostConnection/saveSelfHosted. ===== -->
					<div v-else-if="state.step === 'selfhost'">
						<h1 class="jv-ob-h1">Connect your openclaw</h1>
						<p class="jv-ob-sub">Point Jarvis at <b>your own</b> openclaw server. Jarvis connects over HTTP
							with a bearer token — no Aerele persona/skills. Validate first, then connect.</p>
						<label class="jv-ob-label" for="jv-ob-sh-url">openclaw URL</label>
						<input id="jv-ob-sh-url" class="jv-ob-input" type="text" v-model="state.shUrl"
							   placeholder="http://host.docker.internal:19060">
						<label class="jv-ob-label" for="jv-ob-sh-token">Gateway token</label>
						<input id="jv-ob-sh-token" class="jv-ob-input" type="password" v-model="state.shToken"
							   placeholder="paste your openclaw gateway token" autocomplete="off">
						<label class="jv-ob-check"><input type="checkbox" v-model="state.shStream"> Stream responses token-by-token (recommended)</label>
						<label class="jv-ob-check"><input type="checkbox" v-model="state.shDeep"> Run deep chat test (slower — sends one message)</label>
						<div class="jv-ob-placeholder-actions" style="margin-top:14px;justify-content:flex-start">
							<button class="jv-ob-btn" :disabled="state.shTestBusy" @click="runSelfHostTest">
								{{ state.shTestBusy ? "Testing…" : "Test connection" }}
							</button>
						</div>
						<div v-if="state.shTestBusy" class="jv-ob-note">Testing…</div>
						<div v-else-if="state.shTestResult" class="jv-ob-sh-results">
							<div :class="state.shTestResult.ok ? 'jv-ob-sh-ok' : 'jv-ob-sh-bad'">
								{{ state.shTestResult.ok ? "All required checks passed." : "Some checks failed — fix them and retry." }}
							</div>
							<div v-for="(c, i) in (state.shTestResult.checks || [])" :key="i" class="jv-ob-sh-check" :class="{ 'jv-ob-sh-check-adv': c.advisory }">
								{{ c.ok ? "✅" : (c.advisory ? "⚠️" : "❌") }} <b>{{ c.check }}</b> — {{ c.detail || "" }}<span v-if="c.advisory" class="jv-ob-sh-adv-tag"> · advisory</span>
							</div>
						</div>
						<div v-if="state.shWarning" class="jv-ob-devnote">{{ state.shWarning }}</div>
						<div class="jv-ob-err" role="alert" aria-live="polite">{{ state.shErr }}</div>
						<div v-if="state.finishing" class="jv-ob-note">Finishing setup…</div>
						<div v-else-if="state.finishNote" class="jv-ob-note">
							<span>{{ state.finishNote }}</span>
							<button class="jv-ob-btn jv-ob-btn-primary" @click="forceContinue">Continue to Jarvis →</button>
						</div>
						<div class="jv-ob-placeholder-actions">
							<button class="jv-ob-btn" :disabled="state.shSaveBusy" @click="goBack">← Back</button>
							<button class="jv-ob-btn jv-ob-btn-primary" :disabled="state.shSaveBusy" @click="onSelfHostSave">
								{{ state.shSaveBusy ? "Connecting…" : "Connect →" }}
							</button>
						</div>
					</div>
				</div>
			</div>
			</div>
		</main>
	</div>
</template>

<script setup>
import { reactive, ref, computed, onMounted, watch } from "vue"
import { call } from "frappe-ui"
import { useTheme } from "@/composables/useTheme"
import LlmPoolEditor from "@/components/LlmPoolEditor.vue"
import { STEPS_MANAGED, STEPS_SELFHOST, nextStep, prevStep, stepIndex } from "@/onboarding/steps"
import {
	checkSignupPaymentState, isReadyForChat,
	listPlans, startSignup, finishPayment, devOnboard,
	saveSelfHosted, testSelfHostConnection, getAccountDefaults, syncConnection,
} from "@/api"
import { planPriceLabel } from "@/account/format.js"
import { errMessage as errMsg } from "@/lib/errors"

const { effectiveDark: dark, paletteVars } = useTheme()


// Mirrors jarvis_onboarding.js's STEP_NAMES (~line 212) — the 4 named steps
// shown in managed mode. "mode" and "selfhost" have no header entry.
const STEP_NAMES = ["Account", "Plan", "Pay", "Connect AI"]

// ---- step machine -----------------------------------------------------------
// `state.step` is one of STEPS_MANAGED/STEPS_SELFHOST depending on `state.mode`.
// Kept intentionally small here — Tasks 3-5 add fields as their panels need
// them (email/company/plan choice/etc.), same shape as the desk `state` object.
const state = reactive({
	mode: null, step: "mode",
	// account (renderAccount)
	email: "", company: "", companies: [], accountErr: "",
	// plan (renderPlan)
	plans: [], planName: null, plansLoading: false, plansErr: "",
	// pay (renderPay / renderVerifyEmail / startPay / openCheckout / devOnboard)
	payPhase: "review", // "review" | "verify" — mirrors desk's step-3 vs "check your email" sub-screen
	payErr: "", payBusy: false,
	devActive: null, // UX-only mirror of desk's boot-time `dev`; null until probed on entering "pay"
	successData: null,
	// provisioning gate: after pay, the openclaw container is still spinning up.
	// We block entry to the Connect-AI step until it's running (else save_llm_pool
	// has no container to configure).
	provisioning: false, provisionErr: "",
	// post-save readiness recheck (Connect-AI + self-host both funnel through
	// afterSaveRecheckReady/forceContinue below)
	finishing: false, finishNote: "",
	// self-host (renderSelfHost / renderShResults, jarvis_onboarding.js ~296-376)
	shUrl: "", shToken: "", shStream: true, shDeep: false,
	shTestBusy: false, shTestResult: null, shSaveBusy: false,
	shErr: "", shWarning: "",
})
const accountBusy = ref(false)

const steps = computed(() => (state.mode === "selfhost" ? STEPS_SELFHOST : STEPS_MANAGED))
const selectedPlan = computed(() => state.plans.find((p) => p.name === state.planName) || {})

// 1-based position within the 4 named managed steps (Account=1 … Connect AI=4),
// matching desk's `state.step` numbering used by renderSteps/STEP_NAMES. Index
// 0 ("mode") intentionally renders as 0 — the header is hidden for that step.
const managedStepNum = computed(() => stepIndex(steps.value, state.step))

function goNext() {
	state.step = nextStep(steps.value, state.step)
}
function goBack() {
	state.step = prevStep(steps.value, state.step)
}
// Entry point from the mode-choice screen: record the choice, then advance
// to that track's first real step ("account" for managed, "selfhost" for
// self-host) — mirrors desk's `state.mode = "managed"; go(1)` on mode pick.
function setMode(m) {
	state.mode = m
	goNext()
}

// ---- on-mount reconcile: resume a mid-flight signup ------------------------
// Desk's boot (jarvis_onboarding.js bootRender, ~1699) only checks
// is_onboarded/is_ready_for_chat to decide wizard-vs-completion-card; the
// router's first-run guard (Task 1) already does that before this view ever
// mounts. What desk does NOT do at boot is poll check_signup_payment_state —
// that's only called interactively from the "verify your email" screen
// (jarvis_onboarding.js ~1615). So there's no literal desk boot-time
// reconcile to mirror for "signup started but not finished, then the tab
// was closed/reloaded".
//
// Best-effort reconcile for that gap: use is_ready_for_chat's `reason` to
// pick the right track/step, then (for the managed "signup not done yet"
// case) poll check_signup_payment_state to see whether there's a live
// order/verification to resume. Fails open on any error (no admin URL
// configured yet, not a System Manager, admin API unreachable are all
// expected on a genuine first run) — falls back to the default "mode" step.
//
// RESOLVED (was a CONCERN in task-2-report.md, "revisit once Task 4 builds
// the real pay panel"): check_signup_payment_state is, on desk, ONLY ever
// called from the "check your email" screen (renderVerifyEmail's "I've
// verified" button, jarvis_onboarding.js ~1612) — never from a fresh
// pay-review screen. So EITHER truthy result here (a live razorpay_order_id,
// or still-pending_verification) maps to that same desk sub-screen, not to
// the plan-review screen (which would re-call start_signup — untested for
// idempotency and not a real desk code path) and not to "account" (a plain
// mis-mapping in the original scaffold). onVerifyCheck() below re-polls
// check_signup_payment_state itself and branches on the same two fields, so
// landing here in "verify" phase re-derives the correct next action either
// way. Known gap: email/company/plan text are blank on a resumed session
// (never persisted) until the customer re-verifies — cosmetic only, doesn't
// block the resume.
async function reconcileMidFlightSignup() {
	try {
		const ready = await isReadyForChat()
		if (ready && ready.reason === "selfhost_connection") {
			state.mode = "selfhost"
			state.step = "selfhost"
			return
		}
		if (ready && ready.reason === "llm_credentials") {
			// Signup + payment already done; only the AI connection is missing.
			state.mode = "managed"
			state.step = "connect"
			return
		}
		// reason === "signup" (or call failed) — no completed signup yet, but
		// one may still be mid-flight (started, awaiting verification/payment).
		const pay = await checkSignupPaymentState()
		if (pay && (pay.razorpay_order_id || pay.pending_verification)) {
			state.mode = "managed"
			state.step = "pay"
			state.payPhase = "verify"
		}
		// else: nothing in flight — leave the default "mode" step.
	} catch (e) {
		// Fail-open — never block the wizard from rendering.
	}
}

// ---- Account (renderAccount, jarvis_onboarding.js ~378) --------------------
// Validation matches desk verbatim: email regex + non-empty company. Desk
// also loads the plan list before advancing (loadPlansThen) so step 2 never
// shows a loading flash; mirrored here as a same-click await.
async function onAccountSubmit() {
	state.accountErr = ""
	state.email = (state.email || "").trim()
	state.company = (state.company || "").trim()
	if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(state.email)) {
		state.accountErr = "Enter a valid email address."
		return
	}
	if (!state.company) {
		state.accountErr = "Company name is required."
		return
	}
	accountBusy.value = true
	try {
		if (!state.plans.length) await loadPlans()
		goNext()
	} catch (e) {
		state.accountErr = "Couldn't load plans: " + errMsg(e)
	} finally {
		accountBusy.value = false
	}
}

// ---- Plan (renderPlan, jarvis_onboarding.js ~481) ---------------------------
async function loadPlans() {
	state.plansErr = ""
	state.plansLoading = true
	try {
		state.plans = (await listPlans()) || []
	} finally {
		state.plansLoading = false
	}
}
// Feature list parsing matches desk's renderPlan card body verbatim.
function planFeatures(p) {
	return String((p && p.features) || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
}
function onPlanContinue() {
	if (!state.planName) return
	state.payPhase = "review"
	state.payErr = ""
	goNext()
}

// ---- Pay (renderPay / renderVerifyEmail / startPay / openCheckout /
// devOnboard, jarvis_onboarding.js ~515 & ~1575-1682) ------------------------

// Lazy-load the Razorpay Checkout script (mirrors desk's page-load
// `frappe.require("https://checkout.razorpay.com/v1/checkout.js")`, ~line 18)
// as a promise so openCheckout() can await it instead of racing window.Razorpay.
let razorpayLoadPromise = null
function ensureRazorpayLoaded() {
	if (window.Razorpay) return Promise.resolve()
	if (razorpayLoadPromise) return razorpayLoadPromise
	razorpayLoadPromise = new Promise((resolve, reject) => {
		const s = document.createElement("script")
		s.src = "https://checkout.razorpay.com/v1/checkout.js"
		s.onload = () => resolve()
		s.onerror = () => { razorpayLoadPromise = null; reject(new Error("Couldn't load the Razorpay checkout script.")) }
		document.head.appendChild(s)
	})
	return razorpayLoadPromise
}

// Probe `jarvis.dev.is_dev_mode_active` once on entering the Pay step, purely
// for the heading/button copy — the SPA's boot payload (jarvis/www/jarvis.py)
// doesn't carry an equivalent of desk's boot-time `frappe.boot.jarvis_sandbox_mode`,
// so this RPC stands in for that cosmetic read. Preload the checkout script
// unconditionally (harmless if unused) rather than gating it on this same
// value, to avoid a load-race against a slow/failed probe.
async function enterPayStep() {
	ensureRazorpayLoaded().catch(() => { /* surfaced later if actually needed */ })
	try {
		const r = await call("jarvis.dev.is_dev_mode_active")
		state.devActive = !!(r && r.data && r.data.active)
	} catch (e) {
		state.devActive = false
	}
}

// Click handler for the single Pay/Dev-signup button. Server-authoritative
// branch: re-query is_dev_mode_active at CLICK time, not the cached
// state.devActive — mirrors desk's explicit anti-staleness comment
// (jarvis_onboarding.js ~532-554): a stale "false" must never let this
// silently skip payment when sandbox mode was actually flipped on, and a
// stale cached "true" must never skip a real charge either.
async function onPayClick() {
	state.payErr = ""
	state.payBusy = true
	let isDev = !!state.devActive
	try {
		const r = await call("jarvis.dev.is_dev_mode_active")
		isDev = !!(r && r.data && r.data.active)
	} catch (e) {
		// Server unreachable — fall back to the best-effort cosmetic value,
		// same as desk's catch branch.
	}
	if (isDev) await runDevOnboard()
	else await runStartPay()
}

async function runDevOnboard() {
	try {
		state.successData = await devOnboard(state.email, state.company, state.planName)
		state.payBusy = false
		await proceedAfterPay() // gate on provisioning before → "connect"
	} catch (e) {
		state.payBusy = false
		state.payErr = errMsg(e)
	}
}

function _sleep(ms) { return new Promise((r) => setTimeout(r, ms)) }

// Provisioning gate: after pay, the openclaw container is still spinning up.
// Don't enter Connect-AI until it's running — otherwise save_llm_pool there has
// no container to configure. If pay already returned a running tenant, advance
// immediately; otherwise poll sync_connection until the container is ready.
async function proceedAfterPay() {
	const sd = state.successData || {}
	if (sd.agent_url || sd.tenant_status === "running") { goNext(); return }
	state.provisioning = true
	state.provisionErr = ""
	for (let i = 0; i < 45; i++) {   // ~45 × 2s ≈ 90s
		try {
			const r = await syncConnection()
			if (r && (r.synced || r.tenant_status === "running")) {
				state.provisioning = false
				goNext()
				return
			}
		} catch (e) { /* transient admin/agent hiccup — keep polling */ }
		await _sleep(2000)
	}
	state.provisioning = false
	state.provisionErr = "Your workspace is still being set up — this can take a minute. Retry when you're ready."
}

async function runStartPay() {
	try {
		const d = await startSignup(state.email, state.company, state.planName)
		if (d && d.pending_verification) {
			state.payPhase = "verify"
			state.payBusy = false
			return
		}
		await openCheckout(d)
	} catch (e) {
		state.payBusy = false
		state.payErr = errMsg(e)
	}
}

// Mirrors desk's "I've verified my email" click handler (renderVerifyEmail,
// jarvis_onboarding.js ~1612): re-poll check_signup_payment_state and branch
// on the same two fields desk checks, in the same order.
async function onVerifyCheck() {
	state.payErr = ""
	state.payBusy = true
	try {
		const d = await checkSignupPaymentState()
		if (d && d.pending_verification) {
			state.payBusy = false
			state.payErr = "We haven't received your verification yet. Click the link in your email, then try again."
			return
		}
		if (d && d.razorpay_order_id) {
			await openCheckout(d)
			return
		}
		state.payBusy = false
		state.payErr = "Signup state has changed. Refresh this page to continue."
	} catch (e) {
		state.payBusy = false
		state.payErr = errMsg(e)
	}
}

// Razorpay Checkout — options object + success handler ported verbatim from
// desk openCheckout (jarvis_onboarding.js ~1646-1676). See task-4-report.md
// for the field-by-field comparison against the desk source.
async function openCheckout(d) {
	try {
		await ensureRazorpayLoaded()
	} catch (e) {
		state.payBusy = false
		state.payErr = "Couldn't load the payment form. Check your connection and try again."
		return
	}
	state.payBusy = false
	const rz = new window.Razorpay({
		key: d.razorpay_key_id,
		order_id: d.razorpay_order_id,
		name: "Jarvis",
		description: "Jarvis subscription",
		handler: (res) => {
			state.payBusy = true
			finishPayment({
				razorpay_payment_id: res.razorpay_payment_id,
				razorpay_order_id: res.razorpay_order_id,
				razorpay_signature: res.razorpay_signature,
			}).then((rr) => {
				state.successData = rr
				state.payBusy = false
				proceedAfterPay() // gate on provisioning before → "connect"
			}).catch((e) => {
				state.payBusy = false
				state.payErr = errMsg(e)
			})
		},
		// Razorpay dismiss (customer closed Checkout without paying) — same
		// message as desk's modal.ondismiss, shown inline instead of via
		// frappe.show_alert (no toast primitive on this surface yet).
		modal: {
			ondismiss: () => {
				state.payBusy = false
				state.payErr = "Payment cancelled. Click Pay to try again."
			},
		},
	})
	rz.open()
}

// ---- post-save readiness recheck (Connect-AI + self-host) ------------------
// CRITICAL: the router's first-run guard (router/index.js) caches its
// is_ready_for_chat probe in a module-level `readyPromise` for the lifetime
// of the page — it never invalidates mid-session. So a plain
// `router.push({ name: "Chat" })` right after completing onboarding would
// read that STALE "not ready" cache and bounce straight back to
// /onboarding. Both completion paths (onConnected below and
// onSelfHostSave) instead do a FULL PAGE RELOAD via
// window.location.assign("/jarvis/") once ready, which re-imports the
// router module from scratch and re-runs the readiness check fresh.
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// Poll is_ready_for_chat a few times (short backoff) rather than trusting a
// single check — the save itself (pool save or self-host connect) can
// return before whatever it kicked off (e.g. proxy provisioning) is fully
// reflected. Fails closed (returns false) on a persistent error; callers
// treat "not ready yet" as advisory, not fatal — see finishNote below.
async function waitUntilReady(attempts = 5, delayMs = 800) {
	for (let i = 0; i < attempts; i++) {
		try {
			const r = await isReadyForChat()
			if (r && r.ready) return true
		} catch (e) {
			// keep retrying — transient network hiccups shouldn't strand the user
		}
		if (i < attempts - 1) await sleep(delayMs)
	}
	return false
}

// Manual fallback for the "still not ready" case: never hard-block. The
// customer can always force their way to Chat; if something's genuinely
// still missing, Chat/Account will surface that.
function forceContinue() {
	window.location.assign("/jarvis/")
}

// Shared tail for both completion paths: poll for readiness, then either
// auto-reload (the common case) or leave a "still finishing" note with a
// manual continue button so the user is never stuck staring at a spinner.
async function afterSaveRecheckReady() {
	state.finishNote = ""
	state.finishing = true
	const ready = await waitUntilReady()
	state.finishing = false
	if (ready) {
		window.location.assign("/jarvis/")
		return
	}
	state.finishNote = "Still finishing setup — this can take a few seconds. You can continue to Jarvis now, or wait and try again."
}

// ---- Connect AI (renders <LlmPoolEditor>, jarvis_onboarding.js ~559-1080
// renderLlm) — the component itself owns Quick/Preset/Custom + save_llm_pool;
// this is only the post-save readiness handoff. ---------------------------
function onConnected(sync) {
	afterSaveRecheckReady()
}

// The Connect-AI footer (Back + Save) lives here, not inside LlmPoolEditor
// (:footerless), so it matches every other step's footer. Save is triggered on
// the editor via its exposed save() method.
const poolRef = ref(null)
const savingConnect = ref(false)
// True once the embedded editor reports a savable config (account connected, or
// API key filled) — drives the "Onboard Jarvis" attention pulse.
const connectReady = ref(false)
async function saveConnect() {
	if (!poolRef.value) return
	savingConnect.value = true
	try { await poolRef.value.save() } finally { savingConnect.value = false }
}

// ---- Self-host (renderSelfHost / renderShResults / runSelfHostTest /
// saveSelfHost, jarvis_onboarding.js ~296-376) --------------------------------
async function runSelfHostTest() {
	state.shErr = ""
	const url = (state.shUrl || "").trim()
	if (!url) {
		state.shErr = "Enter the openclaw URL first."
		return
	}
	state.shTestBusy = true
	state.shTestResult = null
	try {
		const r = await testSelfHostConnection({
			base_url: url,
			token: (state.shToken || "").trim(),
			deep: state.shDeep ? 1 : 0,
		})
		state.shTestResult = r || {}
	} catch (e) {
		state.shErr = errMsg(e)
	} finally {
		state.shTestBusy = false
	}
}

async function onSelfHostSave() {
	state.shErr = ""
	state.shWarning = ""
	const url = (state.shUrl || "").trim()
	const tok = (state.shToken || "").trim()
	if (!url || !tok) {
		state.shErr = "openclaw URL and gateway token are both required."
		return
	}
	state.shSaveBusy = true
	try {
		const r = await saveSelfHosted({
			base_url: url, token: tok,
			deep: state.shDeep ? 1 : 0, stream: state.shStream ? 1 : 0,
		})
		const m = r || {}
		state.shSaveBusy = false
		if (m.ok) {
			// Advisory only (e.g. no Self-Host Tool User set yet) — the connection
			// itself is already saved, so this doesn't block the readiness recheck.
			if (m.warning) state.shWarning = m.warning
			await afterSaveRecheckReady()
		} else {
			state.shTestResult = m.result || {}
			state.shErr = "Validation failed — fix the checks above, then retry."
		}
	} catch (e) {
		state.shSaveBusy = false
		state.shErr = errMsg(e)
	}
}

// Enter-step triggers: load the plan list on reaching "plan" (defensive —
// normally already loaded by onAccountSubmit, but also covers a reconcile
// that lands directly on "plan"), and probe dev-mode + preload Razorpay on
// reaching "pay".
watch(() => state.step, (s) => {
	if (s === "plan" && !state.plans.length && !state.plansLoading) {
		loadPlans().catch((e) => { state.plansErr = errMsg(e) })
	}
	if (s === "pay") enterPayStep()
})

// Prefill the Account step from what the site already knows (caller's email +
// default/sole company; datalist for several) so the customer doesn't retype it.
// Backend-sourced because the SPA has no frappe.defaults. Never overwrites a
// value the user already typed; silent on any failure.
async function prefillAccount() {
	try {
		const d = (await getAccountDefaults()) || {}
		if (d.email && !state.email.trim()) state.email = d.email
		if (d.company && !state.company.trim()) state.company = d.company
		if (Array.isArray(d.companies)) state.companies = d.companies
	} catch (e) { /* no-op: keep the placeholders */ }
}

onMounted(() => {
	reconcileMidFlightSignup()
	prefillAccount()
})
</script>

<style scoped>
.jv-ob-root {
	--rad: 8px;
	font-family: 'Inter', system-ui, sans-serif;
	min-height: 100vh;
	background: var(--surface);
	color: var(--text);
	display: flex;
	flex-direction: column;
	position: relative;
}
/* Framing orbs — fixed behind everything, decorative only. Deep navy/indigo in
   light (consistent with the black/white primary), brighter blue on dark. */
.jv-ob-bg { position: fixed; inset: 0; z-index: 0; overflow: hidden; pointer-events: none; }
.jv-ob-orb { position: absolute; width: min(760px, 66vw); aspect-ratio: 1; border-radius: 50%; filter: blur(14px); }
.jv-ob-orb-tl { left: -180px; top: -170px; background: radial-gradient(circle, rgba(30, 58, 138, .24) 0%, transparent 62%); }
.jv-ob-orb-br { right: -190px; bottom: -190px; background: radial-gradient(circle, rgba(49, 46, 129, .20) 0%, transparent 62%); }
.jv-dark .jv-ob-orb-tl { background: radial-gradient(circle, rgba(59, 130, 246, .22) 0%, transparent 60%); }
.jv-dark .jv-ob-orb-br { background: radial-gradient(circle, rgba(99, 102, 241, .18) 0%, transparent 60%); }
.jv-ob-header {
	position: relative;
	z-index: 1;
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 18px 26px;
	flex: none;
}
.jv-ob-logo {
	width: 28px; height: 28px; flex: none;
	border-radius: 7px; background: var(--blue);
	display: flex; align-items: center; justify-content: center;
	box-shadow: 0 1px 2px rgba(37, 99, 235, .35);
}
.jv-ob-brand { font-size: 14px; font-weight: 600; letter-spacing: -.01em; }
.jv-ob-setup { font-size: 12.5px; color: var(--text-3); border-left: 1px solid var(--border); padding-left: 10px; }
.jv-ob-main {
	position: relative;
	z-index: 1;
	flex: 1;
	min-width: 0;
	overflow-y: auto;
}
/* Fills the viewport so the card centers vertically when short; when a step is
   taller than the viewport it grows and the card top-aligns (scrolls from top,
   no cutoff). */
.jv-ob-center {
	min-height: 100%;
	box-sizing: border-box;
	display: flex;
	align-items: center;
	justify-content: center;
	padding: 40px 24px 64px;
}
.jv-ob-wrap {
	max-width: 1000px;
	width: 100%;
}
.jv-ob-h1 { font-size: 32px; font-weight: 650; letter-spacing: -.02em; margin: 0 0 12px; text-align: center; }
.jv-ob-sub { font-size: 16.5px; color: var(--text-3); margin: 0 0 34px; text-align: center; }

.jv-ob-steps {
	display: flex;
	align-items: center;
	margin-bottom: 28px;
}
.jv-ob-step {
	display: flex;
	align-items: center;
	gap: 7px;
	font-size: 12.5px;
	font-weight: 500;
	color: var(--text-3);
}
.jv-ob-step.active { color: var(--text); font-weight: 600; }
.jv-ob-step.done { color: var(--text-2); }
.jv-ob-step-dot {
	display: flex;
	align-items: center;
	justify-content: center;
	width: 20px;
	height: 20px;
	border-radius: 50%;
	border: 1px solid var(--border-2);
	background: var(--surface);
	font-size: 11px;
	flex: none;
}
.jv-ob-step.active .jv-ob-step-dot { border-color: var(--blue); color: var(--blue); }
.jv-ob-step.done .jv-ob-step-dot { border-color: var(--green-bd); background: var(--green-bg); color: var(--green); }
.jv-ob-step-line {
	flex: 1;
	height: 1px;
	background: var(--border);
	margin: 0 8px;
	min-width: 16px;
}
.jv-ob-step-line.done { background: var(--green-bd); }

.jv-ob-body {
	border: 1px solid var(--border);
	border-radius: 18px;
	padding: 52px 56px;
	background: var(--surface);
	box-shadow: 0 20px 50px -24px rgba(15, 23, 42, .28), 0 4px 12px -6px rgba(15, 23, 42, .10);
}
.jv-dark .jv-ob-body { border-color: var(--border-2); box-shadow: 0 24px 60px -24px rgba(0, 0, 0, .6); }
.jv-ob-placeholder { font-size: 13.5px; color: var(--text-3); margin: 0 0 20px; }
/* Uniform step footer: primary action bottom-right (forward = right in an LTR
   wizard), Back pushed to the left. Single-button footers right-align too. */
.jv-ob-placeholder-actions { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; align-items: center; }
.jv-ob-placeholder-actions .jv-ob-btn:not(.jv-ob-btn-primary) { margin-right: auto; }
.jv-ob-btn {
	font-family: inherit;
	font-size: 13px;
	font-weight: 600;
	padding: 8px 14px;
	border-radius: 8px;
	border: 1px solid var(--border-2);
	background: var(--surface);
	color: var(--text);
	cursor: pointer;
}
.jv-ob-btn:hover { background: var(--surface-2); }
.jv-ob-btn-primary { border-color: var(--blue-bd); background: var(--blue-bg); color: var(--blue); }
/* Attention pulse on the final CTA once the config is ready — a soft expanding
   ring that invites the click. Pauses on hover; off for reduced-motion. */
@keyframes jvObCtaPulse {
	0% { box-shadow: 0 0 0 0 rgba(37, 99, 235, .38); }
	70%, 100% { box-shadow: 0 0 0 7px rgba(37, 99, 235, 0); }
}
.jv-ob-cta-ready { border-color: var(--blue); animation: jvObCtaPulse 1.5s ease-out infinite; }
.jv-ob-cta-ready:hover { animation-play-state: paused; }
@media (prefers-reduced-motion: reduce) { .jv-ob-cta-ready { animation: none; } }

/* ---- mode-choice cards — ported from desk .jo-mode* (jarvis_onboarding.js
   ~1889-1898), theme tokens standing in for the desk's --jarvis-primary /
   --card-bg / --border-color. ---- */
.jv-ob-modes { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 6px; }
.jv-ob-mode {
	display: flex;
	flex-direction: column;
	border: 1px solid var(--border);
	border-radius: 12px;
	padding: 24px 22px;
	background: var(--surface-1);
	transition: border-color .15s, transform .1s;
}
.jv-ob-mode:hover { border-color: var(--blue-bd); transform: translateY(-1px); }
.jv-ob-mode-icon { font-size: 30px; line-height: 1; }
.jv-ob-mode-name { font-size: 18px; font-weight: 700; color: var(--text); margin: 10px 0 12px; }
.jv-ob-mode-feats { list-style: none; padding: 0; margin: 0 0 16px; flex: 1; }
.jv-ob-mode-feats li { display: flex; gap: 7px; font-size: 13.5px; color: var(--text-2); line-height: 1.55; margin-bottom: 9px; }
/* Ticks get a real blue accent (the theme's --blue is near-black by design). */
.jv-ob-tick { color: #2563eb; font-size: 11px; font-weight: 700; margin-top: 2px; flex: none; }
.jv-dark .jv-ob-tick { color: var(--blue); }
/* "Not included" note → danger highlight. The li.jv-ob-mode-warn selector
   out-specifies `.jv-ob-mode-feats li` so the red actually lands (before, the
   feats-li colour silently overrode it). */
.jv-ob-mode-feats li.jv-ob-mode-warn {
	color: var(--red);
	background: var(--red-bg);
	border: 1px solid var(--red-bd);
	border-radius: 9px;
	padding: 9px 11px;
	margin-top: 12px;
	align-items: flex-start;
}
.jv-ob-warn-icon { color: var(--red); margin-right: 4px; flex: none; }
.jv-ob-mode-btn { width: 100%; margin-top: auto; }

/* ---- Account — ported from desk .jo-label/.jo-input (jarvis_onboarding.js
   ~378 renderAccount). ---- */
.jv-ob-label { display: block; font-size: 12.5px; font-weight: 600; color: var(--text-2); margin: 14px 0 6px; }
.jv-ob-label:first-of-type { margin-top: 0; }
.jv-ob-input {
	width: 100%;
	font-family: inherit;
	font-size: 13.5px;
	padding: 9px 12px;
	border-radius: 8px;
	border: 1px solid var(--border-2);
	background: var(--surface);
	color: var(--text);
	box-sizing: border-box;
}
.jv-ob-input:focus { outline: none; border-color: var(--blue-bd); }
.jv-ob-err { font-size: 12.5px; color: var(--red); min-height: 1em; margin: 10px 0; }

/* ---- Plan — ported from desk .jo-plans/.jo-plan (jarvis_onboarding.js ~481
   renderPlan). ---- */
.jv-ob-plans { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 4px 0 20px; }
.jv-ob-plan {
	position: relative;
	border: 1px solid var(--border);
	border-radius: 12px;
	padding: 16px 16px 14px;
	background: var(--surface-1);
	cursor: pointer;
	transition: border-color .15s, transform .1s;
}
.jv-ob-plan:hover { border-color: var(--blue-bd); transform: translateY(-1px); }
.jv-ob-plan.selected { border-color: var(--blue); box-shadow: 0 0 0 1px var(--blue); }
.jv-ob-plan-badge {
	position: absolute; top: 10px; right: 10px;
	width: 18px; height: 18px; border-radius: 50%;
	display: flex; align-items: center; justify-content: center;
	font-size: 10px; color: transparent; background: var(--surface-2);
	border: 1px solid var(--border-2);
}
.jv-ob-plan.selected .jv-ob-plan-badge { color: var(--blue); border-color: var(--blue); background: var(--blue-bg); }
.jv-ob-plan-name { font-size: 15px; font-weight: 700; margin-bottom: 4px; }
.jv-ob-plan-price { font-size: 13px; color: var(--text-2); margin-bottom: 10px; }
.jv-ob-plan-feats { list-style: none; padding: 0; margin: 0; }
.jv-ob-plan-feats li { display: flex; gap: 7px; font-size: 12px; color: var(--text-2); line-height: 1.5; margin-bottom: 5px; }
.jv-ob-muted { color: var(--text-3); }

/* ---- Pay — ported from desk .jo-summary/.jo-row/.jo-devnote
   (jarvis_onboarding.js ~515 renderPay). ---- */
.jv-ob-summary { border: 1px solid var(--border); border-radius: 10px; padding: 4px 14px; margin: 4px 0 14px; }
.jv-ob-row { display: flex; justify-content: space-between; align-items: baseline; padding: 9px 0; font-size: 13px; color: var(--text-3); border-bottom: 1px solid var(--border); }
.jv-ob-row:last-child { border-bottom: none; }
.jv-ob-row b { color: var(--text); font-weight: 600; }
.jv-ob-row-total { font-size: 13.5px; }
.jv-ob-row-total b { font-size: 15px; }
.jv-ob-devnote { font-size: 12.5px; color: var(--amber); background: var(--amber-bg); border: 1px solid var(--amber-bd); border-radius: 8px; padding: 8px 12px; margin-bottom: 14px; }

/* ---- Self-host — ported from desk .jo-check/.jo-sh-* (jarvis_onboarding.js
   ~296-376 renderSelfHost/renderShResults). ---- */
.jv-ob-check { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text); margin-top: 8px; cursor: pointer; }
.jv-ob-sh-results { margin: 14px 0 4px; font-size: 12.5px; line-height: 1.7; }
.jv-ob-sh-check { color: var(--text); }
.jv-ob-sh-check-adv { color: var(--text-3); }
.jv-ob-sh-adv-tag { color: var(--text-3); font-style: italic; }
.jv-ob-sh-ok { color: var(--green); font-weight: 600; margin-bottom: 4px; }
.jv-ob-sh-bad { color: var(--red); font-weight: 600; margin-bottom: 4px; }

/* ---- Connect-AI / self-host post-save readiness note (afterSaveRecheckReady). ---- */
.jv-ob-note { font-size: 12.5px; color: var(--text-3); margin-top: 14px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

@media (max-width: 520px) {
	.jv-ob-main { padding: 28px 16px 48px; }
	.jv-ob-body { padding: 26px 20px; border-radius: 14px; }
	.jv-ob-h1 { font-size: 25px; }
	.jv-ob-sub { font-size: 15px; margin-bottom: 26px; }
	.jv-ob-orb { width: min(520px, 90vw); }
	.jv-ob-modes { grid-template-columns: 1fr; }
	.jv-ob-plans { grid-template-columns: 1fr; }
}
@media (prefers-reduced-motion: reduce) {
	.jv-ob-mode, .jv-ob-plan { transition: none; }
}
</style>
