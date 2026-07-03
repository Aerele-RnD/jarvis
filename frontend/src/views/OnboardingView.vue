<template>
	<div class="jv-app" :class="{ 'jv-dark': dark }" :style="paletteVars"
		 style="display:flex;min-height:100vh;background:var(--surface);color:var(--text);">

		<AppSidebar minimal />

		<main class="jv-ob-main">
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
							   placeholder="Acme Inc." autocomplete="organization" required aria-required="true"
							   @keydown.enter="onAccountSubmit">
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
						<template v-if="state.payPhase === 'verify'">
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

					<div v-else-if="state.step === 'connect'">
						<p class="jv-ob-placeholder">[managed: connect AI panel — Tasks 3-5]</p>
						<div class="jv-ob-placeholder-actions">
							<button class="jv-ob-btn" @click="goBack">← Back</button>
						</div>
					</div>

					<div v-else-if="state.step === 'selfhost'">
						<p class="jv-ob-placeholder">[self-host: connect panel — Tasks 3-5]</p>
						<div class="jv-ob-placeholder-actions">
							<button class="jv-ob-btn" @click="goBack">← Back</button>
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
import AppSidebar from "@/components/AppSidebar.vue"
import { STEPS_MANAGED, STEPS_SELFHOST, nextStep, prevStep, stepIndex } from "@/onboarding/steps"
import {
	checkSignupPaymentState, isReadyForChat,
	listPlans, startSignup, finishPayment, devOnboard,
} from "@/api"
import { planPriceLabel } from "@/account/format.js"

const { effectiveDark: dark, paletteVars } = useTheme()

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

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
	email: "", company: "", accountErr: "",
	// plan (renderPlan)
	plans: [], planName: null, plansLoading: false, plansErr: "",
	// pay (renderPay / renderVerifyEmail / startPay / openCheckout / devOnboard)
	payPhase: "review", // "review" | "verify" — mirrors desk's step-3 vs "check your email" sub-screen
	payErr: "", payBusy: false,
	devActive: null, // UX-only mirror of desk's boot-time `dev`; null until probed on entering "pay"
	successData: null,
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
		goNext() // → "connect"
	} catch (e) {
		state.payBusy = false
		state.payErr = errMsg(e)
	}
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
				goNext() // → "connect"
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

onMounted(() => {
	reconcileMidFlightSignup()
})
</script>

<style scoped>
.jv-ob-main {
	flex: 1;
	min-width: 0;
	overflow-y: auto;
	height: 100vh;
	padding: 48px 32px 60px;
}
.jv-ob-wrap {
	max-width: 640px;
	margin: 0;
}
.jv-ob-h1 { font-size: 20px; font-weight: 600; margin: 0 0 8px; }
.jv-ob-sub { font-size: 13.5px; color: var(--text-3); margin: 0 0 20px; }

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
	border-radius: 12px;
	padding: 24px 26px;
	background: var(--surface);
}
.jv-ob-placeholder { font-size: 13.5px; color: var(--text-3); margin: 0 0 20px; }
.jv-ob-placeholder-actions { display: flex; gap: 10px; flex-wrap: wrap; }
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

/* ---- mode-choice cards — ported from desk .jo-mode* (jarvis_onboarding.js
   ~1889-1898), theme tokens standing in for the desk's --jarvis-primary /
   --card-bg / --border-color. ---- */
.jv-ob-modes { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 4px; }
.jv-ob-mode {
	display: flex;
	flex-direction: column;
	border: 1px solid var(--border);
	border-radius: 12px;
	padding: 18px 16px;
	background: var(--surface-1);
	transition: border-color .15s, transform .1s;
}
.jv-ob-mode:hover { border-color: var(--blue-bd); transform: translateY(-1px); }
.jv-ob-mode-icon { font-size: 26px; line-height: 1; }
.jv-ob-mode-name { font-size: 16px; font-weight: 700; color: var(--text); margin: 8px 0 10px; }
.jv-ob-mode-feats { list-style: none; padding: 0; margin: 0 0 16px; flex: 1; }
.jv-ob-mode-feats li { display: flex; gap: 7px; font-size: 12.5px; color: var(--text-2); line-height: 1.5; margin-bottom: 7px; }
.jv-ob-tick { color: var(--blue); font-size: 11px; margin-top: 2px; flex: none; }
.jv-ob-mode-warn { color: var(--red); margin-top: 8px; }
.jv-ob-warn-icon { margin-right: 4px; flex: none; }
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

@media (max-width: 520px) {
	.jv-ob-main { padding: 28px 16px 48px; }
	.jv-ob-body { padding: 18px; }
	.jv-ob-modes { grid-template-columns: 1fr; }
	.jv-ob-plans { grid-template-columns: 1fr; }
}
</style>
