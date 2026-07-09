<template>
	<div class="jv-ob-root" :class="{ 'jv-dark': dark }" :style="paletteVars">

		<!-- Framing orbs: two quiet deep-blue orbs settle into the empty corners and
			 frame the wizard without touching it. Decorative only (aria-hidden, no
			 pointer events). -->
		<div class="jv-ob-bg" aria-hidden="true">
			<div class="jv-ob-orb jv-ob-orb-tl"></div>
			<div class="jv-ob-orb jv-ob-orb-br"></div>
		</div>

		<main class="jv-ob-main">
			<div class="jv-ob-center">
				<div class="jv-ob-wrap">

					<!-- brand header: JarvisMark + name + per-step subtitle (preview .brand) -->
					<div class="jv-ob-brand">
						<span class="jv-ob-logo"><svg width="17" height="17" viewBox="0 0 24 24" fill="#fff"><path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" /></svg></span>
						<span class="jv-ob-brand-name">Jarvis</span>
						<span class="jv-ob-brand-sub">{{ frameSub }}</span>
					</div>

					<!-- step rail: Plan · Details · Pay · Connect. Hidden on the intro
						 tour (chromeless) and on the single-step self-host track. -->
					<div v-if="railIndex >= 0" class="jv-ob-steps">
						<template v-for="(s, i) in RAIL" :key="s.id">
							<span class="jv-ob-step" :class="{ done: i < railIndex, active: i === railIndex }">
								<span class="jv-ob-step-dot">{{ i < railIndex ? "✓" : i + 1 }}</span>{{ s.label }}
							</span>
							<span v-if="i < RAIL.length - 1" class="jv-ob-step-line" :class="{ done: i < railIndex }"></span>
						</template>
					</div>

					<div class="jv-ob-panel">

						<!-- ===== Intro tour (fresh starts only; reconcile routes mid-flight
							 signups straight to the right step, past the tour) ===== -->
						<TourIntro v-if="state.step === 'intro'" @finish="startWizard" @skip="startWizard" />

						<!-- ===== Choose Your Plan ===== -->
						<section v-else-if="state.step === 'plan'" class="jv-ob-screen">
							<div class="jv-ob-body">
								<div class="jv-ob-head">
									<h1>Choose Your Plan</h1>
									<p>Start free. Upgrade or extend anytime, with no auto-renewal.</p>
								</div>
								<div v-if="state.plansLoading" class="jv-ob-placeholder">Loading plans…</div>
								<div v-else-if="state.plansErr" class="jv-ob-err">{{ state.plansErr }}</div>
								<div v-else-if="!state.plans.length" class="jv-ob-placeholder">No plans are available right now. Please contact support.</div>
								<div v-else class="jv-ob-plans" role="radiogroup" aria-label="Plan">
									<div v-for="(p, i) in state.plans" :key="p.name" class="jv-ob-plan"
										 :class="{ sel: state.planName === p.name }" role="radio"
										 :aria-checked="state.planName === p.name" tabindex="0"
										 @click="state.planName = p.name"
										 @keydown.enter.prevent="state.planName = p.name"
										 @keydown.space.prevent="state.planName = p.name">
										<div v-if="i === popularIndex" class="jv-ob-plan-tag">Popular</div>
										<div class="jv-ob-plan-rd"></div>
										<div class="jv-ob-plan-nm">{{ p.plan_name }}</div>
										<div class="jv-ob-plan-pr">{{ planAmount(p) }}<span v-if="planSuffix(p)"> {{ planSuffix(p) }}</span></div>
										<div class="jv-ob-plan-cyc">{{ planCycleLabel(p) }}</div>
										<ul>
											<li v-for="(f, k) in planFeatures(p)" :key="k"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>{{ f }}</li>
											<li v-if="!planFeatures(p).length" class="jv-ob-muted">{{ p.billing_cycle }} plan</li>
										</ul>
									</div>
								</div>
							</div>
							<div class="jv-ob-foot">
								<button class="jv-ob-back" @click="goBack">← Back to tour</button>
								<button class="jv-ob-link" @click="enterSelfhost">Self-hosted? Connect your own openclaw</button>
								<button class="jv-ob-btn jv-ob-btn-primary" :disabled="!state.planName" @click="onPlanContinue">Continue →</button>
							</div>
						</section>

						<!-- ===== Your Details ===== -->
						<section v-else-if="state.step === 'details'" class="jv-ob-screen">
							<div class="jv-ob-body">
								<div class="jv-ob-head">
									<h1>Your Details</h1>
									<p>We'll set Jarvis up for this workspace and send receipts here.</p>
								</div>
								<div class="jv-ob-form">
									<div class="jv-ob-sec-label">Account</div>
									<div class="jv-ob-field">
										<label for="jv-ob-email">Work email</label>
										<input id="jv-ob-email" class="jv-ob-inp" type="email" v-model="state.email"
											   placeholder="you@company.com" autocomplete="email" required aria-required="true"
											   @keydown.enter="onDetailsSubmit">
									</div>
									<div class="jv-ob-field">
										<label for="jv-ob-contact">Contact number</label>
										<input id="jv-ob-contact" class="jv-ob-inp" type="tel" v-model="state.contact"
											   placeholder="+91 98765 43210" autocomplete="tel"
											   @keydown.enter="onDetailsSubmit">
									</div>
									<div class="jv-ob-field jv-ob-field-full">
										<label for="jv-ob-company">Company</label>
										<JvCombo id="jv-ob-company" :model-value="state.company" @update:model-value="(v) => state.company = v"
												 allow-custom aria-required autocomplete="organization" :options="state.companies"
												 placeholder="Acme Inc." @enter="onDetailsSubmit" />
									</div>
									<div class="jv-ob-sec-label">Billing</div>
									<div class="jv-ob-field jv-ob-field-full">
										<label for="jv-ob-addr">Billing address</label>
										<input id="jv-ob-addr" class="jv-ob-inp" type="text" v-model="state.billingAddress"
											   placeholder="Street, area" autocomplete="street-address"
											   @keydown.enter="onDetailsSubmit">
									</div>
									<div class="jv-ob-field">
										<label for="jv-ob-city">City</label>
										<input id="jv-ob-city" class="jv-ob-inp" type="text" v-model="state.city"
											   placeholder="Chennai" autocomplete="address-level2"
											   @keydown.enter="onDetailsSubmit">
									</div>
									<div class="jv-ob-field">
										<label for="jv-ob-gstin">GSTIN <span class="jv-ob-opt">(optional)</span></label>
										<input id="jv-ob-gstin" class="jv-ob-inp" type="text" v-model="state.gstin"
											   placeholder="33ABCDE1234F1Z5" @keydown.enter="onDetailsSubmit">
									</div>
								</div>
								<div class="jv-ob-err jv-ob-err-center" role="alert" aria-live="polite">{{ state.detailsErr }}</div>
							</div>
							<div class="jv-ob-foot">
								<button class="jv-ob-back" @click="goBack">← Back</button>
								<button class="jv-ob-btn jv-ob-btn-primary" @click="onDetailsSubmit">Continue →</button>
							</div>
						</section>

						<!-- ===== Review & Pay (renderPay / renderVerifyEmail / startPay /
							 openCheckout / devOnboard preserved verbatim in behavior) ===== -->
						<section v-else-if="state.step === 'pay'" class="jv-ob-screen">
							<template v-if="state.provisioning || state.provisionErr">
								<div class="jv-ob-body">
									<div class="jv-ob-head">
										<h1>Setting up your workspace</h1>
										<p v-if="state.provisioning">Payment received. We're provisioning your Jarvis workspace. This usually takes under a minute…</p>
									</div>
									<div v-if="state.provisioning" class="jv-ob-spinner" aria-hidden="true"></div>
									<p v-if="state.provisionErr" class="jv-ob-err jv-ob-err-center" role="alert">{{ state.provisionErr }}</p>
								</div>
								<div v-if="state.provisionErr" class="jv-ob-foot jv-ob-foot-end">
									<button class="jv-ob-btn jv-ob-btn-primary" @click="proceedAfterPay">Retry</button>
								</div>
							</template>
							<template v-else-if="state.payPhase === 'verify'">
								<div class="jv-ob-body">
									<div class="jv-ob-head">
										<h1>Check your email</h1>
										<p>We sent a confirmation link to <b>{{ state.email || "your email" }}</b>.
											Click the link to verify your address, then come back here and click the button below
											to continue to payment.</p>
									</div>
									<p class="jv-ob-hint">The link expires in 24 hours. Check your spam folder if it doesn't arrive.</p>
									<div class="jv-ob-err jv-ob-err-center">{{ state.payErr }}</div>
								</div>
								<div class="jv-ob-foot jv-ob-foot-end">
									<button class="jv-ob-btn jv-ob-btn-primary" :disabled="state.payBusy" @click="onVerifyCheck">
										{{ state.payBusy ? "Working…" : "I've verified my email →" }}
									</button>
								</div>
							</template>
							<template v-else-if="state.successData">
								<div class="jv-ob-body">
									<div class="jv-ob-head">
										<h1>Payment complete</h1>
										<p>You're all set. Continue to connect your AI.</p>
									</div>
								</div>
								<div class="jv-ob-foot jv-ob-foot-end">
									<button class="jv-ob-btn jv-ob-btn-primary" @click="goNext">Continue →</button>
								</div>
							</template>
							<template v-else>
								<div class="jv-ob-body">
									<div class="jv-ob-head">
										<h1>Review &amp; Pay</h1>
										<p>Confirm the details below. You'll complete payment securely via Razorpay.</p>
									</div>
									<div class="jv-ob-rev">
										<div class="jv-ob-rev-row"><span>Plan</span><b>{{ planRowLabel }}</b></div>
										<div class="jv-ob-rev-row"><span>Company</span><b>{{ state.company }}</b></div>
										<div class="jv-ob-rev-row"><span>Billed to</span><b>{{ state.email }}</b></div>
										<div class="jv-ob-rev-row jv-ob-rev-total"><span>Due today</span><b>{{ dueTodayLabel }}</b></div>
									</div>
									<div class="jv-ob-rev-note">
										<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
										Secured by Razorpay · cards, UPI &amp; netbanking
									</div>
									<div v-if="state.devActive" class="jv-ob-devnote">Developer mode: payment is skipped (dev signup).</div>
									<div class="jv-ob-err jv-ob-err-center">{{ state.payErr }}</div>
								</div>
								<div class="jv-ob-foot">
									<button class="jv-ob-back" :disabled="state.payBusy" @click="goBack">← Back</button>
									<button class="jv-ob-btn jv-ob-btn-primary" :disabled="state.payBusy" @click="onPayClick">
										{{ state.payBusy ? "Working…" : payCta }}
									</button>
								</div>
							</template>
						</section>

						<!-- ===== Connect Your AI (managed) - embeds the shared LlmPoolEditor
							 (same one AccountView uses), :modes="['quick']". The component owns
							 save_llm_pool; this step is the post-save readiness handoff.
							 v-show (not v-if) so the editor stays MOUNTED while its own save()
							 is still awaiting. ===== -->
						<section v-else-if="state.step === 'connect'" class="jv-ob-screen">
							<div class="jv-ob-body">
								<div v-show="state.finishing">
									<div class="jv-ob-head">
										<h1>Setting up Jarvis</h1>
										<p>Bringing your workspace online, taking you to chat…</p>
									</div>
									<div class="jv-ob-spinner" aria-hidden="true"></div>
								</div>
								<div v-show="!state.finishing">
									<div class="jv-ob-head">
										<h1>Connect Your AI</h1>
										<p>Pick which AI powers Jarvis. You can change this anytime from Settings.</p>
									</div>
									<div class="jv-ob-connect">
										<LlmPoolEditor ref="poolRef" :editable="true" :modes="['quick']" :footerless="true" @saved="onConnected" @ready="connectReady = $event" />
									</div>
									<div v-if="state.finishNote" class="jv-ob-note">
										<span>{{ state.finishNote }}</span>
										<button class="jv-ob-btn jv-ob-btn-primary" @click="forceContinue">Continue to Jarvis →</button>
									</div>
								</div>
							</div>
							<div v-if="!state.finishing" class="jv-ob-foot">
								<button class="jv-ob-back" @click="goBack">← Back</button>
								<!-- The ONLY gradient button in the whole flow. -->
								<button v-if="connectReady || savingConnect" class="jv-ob-btn jv-ob-btn-grad" :disabled="savingConnect" @click="saveConnect">
									{{ savingConnect ? "Connecting…" : "Connect & Finish →" }}
								</button>
							</div>
						</section>

						<!-- ===== Self-host (reached via the quiet Plan-step link; logic
							 unchanged, field names/args match test_connection /
							 save_self_hosted verbatim) ===== -->
						<section v-else-if="state.step === 'selfhost'" class="jv-ob-screen">
							<div class="jv-ob-body">
								<div class="jv-ob-head">
									<h1>Connect your openclaw</h1>
									<p>Point Jarvis at <b>your own</b> openclaw server. Jarvis connects over HTTP
										with a bearer token. No Aerele persona/skills. Validate first, then connect.</p>
								</div>
								<div class="jv-ob-sh">
									<label class="jv-ob-label" for="jv-ob-sh-url">openclaw URL</label>
									<input id="jv-ob-sh-url" class="jv-ob-inp" type="text" v-model="state.shUrl"
										   placeholder="http://host.docker.internal:19060">
									<label class="jv-ob-label" for="jv-ob-sh-token">Gateway token</label>
									<input id="jv-ob-sh-token" class="jv-ob-inp" type="password" v-model="state.shToken"
										   placeholder="paste your openclaw gateway token" autocomplete="off">
									<label class="jv-ob-check"><input type="checkbox" v-model="state.shStream"> Stream responses token-by-token (recommended)</label>
									<label class="jv-ob-check"><input type="checkbox" v-model="state.shDeep"> Run deep chat test (slower, sends one message)</label>
									<div class="jv-ob-sh-actions">
										<button class="jv-ob-btn" :disabled="state.shTestBusy" @click="runSelfHostTest">
											{{ state.shTestBusy ? "Testing…" : "Test connection" }}
										</button>
									</div>
									<div v-if="state.shTestBusy" class="jv-ob-note">Testing…</div>
									<div v-else-if="state.shTestResult" class="jv-ob-sh-results">
										<div :class="state.shTestResult.ok ? 'jv-ob-sh-ok' : 'jv-ob-sh-bad'">
											{{ state.shTestResult.ok ? "All required checks passed." : "Some checks failed. Fix them and retry." }}
										</div>
										<div v-for="(c, i) in (state.shTestResult.checks || [])" :key="i" class="jv-ob-sh-check" :class="{ 'jv-ob-sh-check-adv': c.advisory }">
											{{ c.ok ? "✅" : (c.advisory ? "⚠️" : "❌") }} <b>{{ c.check }}</b> · {{ c.detail || "" }}<span v-if="c.advisory" class="jv-ob-sh-adv-tag"> · advisory</span>
										</div>
									</div>
									<div v-if="state.shWarning" class="jv-ob-devnote">{{ state.shWarning }}</div>
									<div class="jv-ob-err" role="alert" aria-live="polite">{{ state.shErr }}</div>
									<div v-if="state.finishing" class="jv-ob-note">Finishing setup…</div>
									<div v-else-if="state.finishNote" class="jv-ob-note">
										<span>{{ state.finishNote }}</span>
										<button class="jv-ob-btn jv-ob-btn-primary" @click="forceContinue">Continue to Jarvis →</button>
									</div>
								</div>
							</div>
							<div class="jv-ob-foot">
								<button class="jv-ob-back" :disabled="state.shSaveBusy" @click="backFromSelfhost">← Back</button>
								<button class="jv-ob-btn jv-ob-btn-primary" :disabled="state.shSaveBusy" @click="onSelfHostSave">
									{{ state.shSaveBusy ? "Connecting…" : "Connect →" }}
								</button>
							</div>
						</section>

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
import JvCombo from "@/components/JvCombo.vue"
import TourIntro from "@/onboarding/TourIntro.vue"
import { STEPS_MANAGED, STEPS_SELFHOST, nextStep, prevStep } from "@/onboarding/steps"
import {
	checkSignupPaymentState, isReadyForChat,
	listPlans, startSignup, finishPayment, devOnboard,
	saveSelfHosted, testSelfHostConnection, getAccountDefaults, syncConnection,
} from "@/api"
import { errMessage as errMsg } from "@/lib/errors"

const { effectiveDark: dark, paletteVars } = useTheme()

// The 4 named wizard steps shown on the rail. The intro tour and the
// self-host track are chromeless (no rail entry).
const RAIL = [
	{ id: "plan", label: "Plan" },
	{ id: "details", label: "Details" },
	{ id: "pay", label: "Pay" },
	{ id: "connect", label: "Connect" },
]

// Frame subtitle next to the brand mark, mirroring the active step's title.
const FRAME_SUBS = {
	intro: "Meet your ERPNext assistant",
	plan: "Choose Your Plan",
	details: "Your Details",
	pay: "Review & Pay",
	connect: "Connect Your AI",
	selfhost: "Self-hosted setup",
}

// ---- step machine -----------------------------------------------------------
// `state.step` walks STEPS_MANAGED (intro → plan → details → pay → connect);
// the self-host track is a side branch entered from the Plan step's quiet link
// (enterSelfhost/backFromSelfhost below) and via reconcile.
const state = reactive({
	mode: "managed", step: "intro",
	// details (Your Details step)
	email: "", company: "", companies: [], detailsErr: "",
	// Collected by the redesign but NOT submitted yet:
	// jarvis.onboarding.start_signup(email, company, plan) and
	// admin_client.signup(email, company_name, plan, coupon=None) accept no
	// contact/billing kwargs, and the admin-side signup contract is external
	// to this repo. Threading them through would break the API contract.
	// TODO(backend): pass contact + billingAddress/city/gstin through
	// start_signup → admin signup once those endpoints accept them.
	contact: "", billingAddress: "", city: "", gstin: "",
	// plan (Choose Your Plan step)
	plans: [], planName: null, plansLoading: false, plansErr: "",
	// pay (renderPay / renderVerifyEmail / startPay / openCheckout / devOnboard)
	payPhase: "review", // "review" | "verify" - mirrors desk's step-3 vs "check your email" sub-screen
	payErr: "", payBusy: false,
	devActive: null, // UX-only mirror of desk's boot-time `dev`; null until probed on entering "pay"
	successData: null,
	// provisioning gate: after pay, the openclaw container is still spinning up.
	// We block entry to the Connect step until it's running (else save_llm_pool
	// has no container to configure).
	provisioning: false, provisionErr: "",
	// post-save readiness recheck (Connect + self-host both funnel through
	// afterSaveRecheckReady/forceContinue below)
	finishing: false, finishNote: "",
	// self-host (renderSelfHost / renderShResults, jarvis_onboarding.js ~296-376)
	shUrl: "", shToken: "", shStream: true, shDeep: false,
	shTestBusy: false, shTestResult: null, shSaveBusy: false,
	shErr: "", shWarning: "",
})

const steps = computed(() => (state.mode === "selfhost" ? STEPS_SELFHOST : STEPS_MANAGED))
const selectedPlan = computed(() => state.plans.find((p) => p.name === state.planName) || {})
const railIndex = computed(() => RAIL.findIndex((r) => r.id === state.step))
const frameSub = computed(() => FRAME_SUBS[state.step] || "Set up your workspace")

// "Popular" highlight: the middle plan when the catalog has 3+ entries (the
// admin catalog has no recommended flag; preview tags the middle card).
const popularIndex = computed(() => (state.plans.length >= 3 ? Math.floor(state.plans.length / 2) : -1))

// Pay CTA copy: dev signup in sandbox; "Pay ₹X →" for a paid plan; plain
// sign-up for a free one.
const payCta = computed(() => {
	if (state.devActive) return "Dev signup & connect"
	const n = Number(selectedPlan.value.price_inr) || 0
	return n > 0 ? `Pay ₹${n.toLocaleString("en-IN")} →` : "Sign up →"
})

// Review-card labels (preview .rev): "Pro · Monthly" plan row and a plain
// amount in the emphasized total row.
const planRowLabel = computed(() => {
	const p = selectedPlan.value
	if (!p.plan_name) return ""
	return p.billing_cycle ? `${p.plan_name} · ${p.billing_cycle}` : p.plan_name
})
const dueTodayLabel = computed(() => `₹${(Number(selectedPlan.value.price_inr) || 0).toLocaleString("en-IN")}`)

function goNext() {
	state.step = nextStep(steps.value, state.step)
}
function goBack() {
	state.step = prevStep(steps.value, state.step)
}
// Intro tour exits (CTA / advancing past the last slide / Skip tour) all land
// on the Plan step.
function startWizard() {
	state.step = "plan"
}
// Self-host is a side branch off the Plan step, not a rail step. Entering and
// leaving it flips `state.mode` so `steps` (and goNext from a reconciled
// selfhost resume) stay coherent.
function enterSelfhost() {
	state.mode = "selfhost"
	state.step = "selfhost"
}
function backFromSelfhost() {
	state.mode = "managed"
	state.step = "plan"
}

// ---- on-mount reconcile: resume a mid-flight signup ------------------------
// A mid-flight signup must land on the right step, NOT the intro tour - the
// tour shows only for a fresh, not-started onboarding (the default "intro"
// step stands when nothing below matches).
//
// Best-effort reconcile: use is_ready_for_chat's `reason` to pick the right
// track/step, then (for the managed "signup not done yet" case) poll
// check_signup_payment_state to see whether there's a live order/verification
// to resume. Fails open on any error (no admin URL configured yet, not a
// System Manager, admin API unreachable are all expected on a genuine first
// run) - falls back to the default "intro" step.
//
// check_signup_payment_state is, on desk, ONLY ever called from the "check
// your email" screen (renderVerifyEmail's "I've verified" button,
// jarvis_onboarding.js ~1612) - never from a fresh pay-review screen. So
// EITHER truthy result here (a live razorpay_order_id, or still-
// pending_verification) maps to that same desk sub-screen, not to the review
// screen (which would re-call start_signup - untested for idempotency and not
// a real desk code path). onVerifyCheck() below re-polls
// check_signup_payment_state itself and branches on the same two fields, so
// landing here in "verify" phase re-derives the correct next action either
// way. Known gap: email/company/plan text are blank on a resumed session
// (never persisted) until the customer re-verifies - cosmetic only.
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
		// reason === "signup" (or call failed) - no completed signup yet, but
		// one may still be mid-flight (started, awaiting verification/payment).
		const pay = await checkSignupPaymentState()
		if (pay && (pay.razorpay_order_id || pay.pending_verification)) {
			state.mode = "managed"
			state.step = "pay"
			state.payPhase = "verify"
		}
		// else: nothing in flight - leave the default "intro" step (fresh start).
	} catch (e) {
		// Fail-open - never block the wizard from rendering.
	}
}

// ---- Plan (Choose Your Plan) ------------------------------------------------
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
// Preview renders the price as a big amount with a small muted "/mo" suffix
// (₹3,999 <span>/mo</span>) instead of one uniform string. Same cycle→suffix
// rule as account/format.js planPriceLabel (everything non-annual is monthly).
function planAmount(p) {
	const n = Number(p && p.price_inr) || 0
	return n > 0 ? `₹${n.toLocaleString("en-IN")}` : "Free"
}
function planSuffix(p) {
	const n = Number(p && p.price_inr) || 0
	if (n <= 0) return ""
	return (p.billing_cycle || "").toLowerCase() === "annual" ? "/yr" : "/mo"
}
// Cycle line under the price, per the approved preview copy ("Billed monthly"
// on paid cards, "For trying Jarvis" on the free one).
function planCycleLabel(p) {
	const n = Number(p && p.price_inr) || 0
	if (n <= 0) return "For trying Jarvis"
	return (p.billing_cycle || "").toLowerCase() === "annual" ? "Billed annually" : "Billed monthly"
}
function onPlanContinue() {
	if (!state.planName) return
	goNext()
}

// ---- Details (Your Details) -------------------------------------------------
// Validation matches the old Account step verbatim: email regex + non-empty
// company. The contact/billing fields are collected but not (yet) submitted -
// see the TODO(backend) note on `state` above.
function onDetailsSubmit() {
	state.detailsErr = ""
	state.email = (state.email || "").trim()
	state.company = (state.company || "").trim()
	if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(state.email)) {
		state.detailsErr = "Enter a valid email address."
		return
	}
	if (!state.company) {
		state.detailsErr = "Company name is required."
		return
	}
	// Entering Review & Pay fresh from Details: reset the pay sub-state.
	state.payPhase = "review"
	state.payErr = ""
	goNext()
}

// ---- Pay (renderPay / renderVerifyEmail / startPay / openCheckout /
// devOnboard, jarvis_onboarding.js ~515 & ~1575-1682) ------------------------
// Signup fires at the Details → Pay boundary via this step's single CTA:
// the customer reviews, clicks once, and that click runs the dev-mode check →
// devOnboard | startSignup → verify-email/checkout branches EXACTLY as the
// desk flow does. start_signup is deliberately NOT fired on step entry: it is
// not idempotent-tested, and Back-then-Continue would re-call it.

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
// for the heading/button copy - the SPA's boot payload (jarvis/www/jarvis.py)
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
// state.devActive - mirrors desk's explicit anti-staleness comment
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
		// Server unreachable - fall back to the best-effort cosmetic value,
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
// Don't enter Connect until it's running - otherwise save_llm_pool there has
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
		} catch (e) { /* transient admin/agent hiccup - keep polling */ }
		await _sleep(2000)
	}
	state.provisioning = false
	state.provisionErr = "Your workspace is still being set up. This can take a minute. Retry when you're ready."
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

// Razorpay Checkout - options object + success handler ported verbatim from
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
		// Razorpay dismiss (customer closed Checkout without paying) - same
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

// ---- post-save readiness recheck (Connect + self-host) ----------------------
// CRITICAL: the router's first-run guard (router/index.js) caches its
// is_ready_for_chat probe in a module-level `readyPromise` for the lifetime
// of the page - it never invalidates mid-session. So a plain
// `router.push({ name: "Chat" })` right after completing onboarding would
// read that STALE "not ready" cache and bounce straight back to
// /onboarding. Both completion paths (onConnected below and
// onSelfHostSave) instead do a FULL PAGE RELOAD via
// window.location.assign("/jarvis/") once ready, which re-imports the
// router module from scratch and re-runs the readiness check fresh.
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// Poll is_ready_for_chat a few times (short backoff) rather than trusting a
// single check - the save itself (pool save or self-host connect) can
// return before whatever it kicked off (e.g. proxy provisioning) is fully
// reflected. Fails closed (returns false) on a persistent error; callers
// treat "not ready yet" as advisory, not fatal - see finishNote below.
async function waitUntilReady(attempts = 5, delayMs = 800) {
	for (let i = 0; i < attempts; i++) {
		try {
			const r = await isReadyForChat()
			if (r && r.ready) return true
		} catch (e) {
			// keep retrying - transient network hiccups shouldn't strand the user
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
	if (ready) {
		// Keep the "Setting up Jarvis" spinner up THROUGH the full-page reload.
		// Flipping finishing off first re-shows the editor for a frame before
		// the browser navigates. Leave it on; location.assign tears the page down.
		window.location.assign("/jarvis/")
		return
	}
	state.finishing = false
	state.finishNote = "Still finishing setup. This can take a few seconds. You can continue to Jarvis now, or wait and try again."
}

// ---- Connect (renders <LlmPoolEditor>) - the component itself owns
// Quick/Preset/Custom + save_llm_pool; this is only the post-save readiness
// handoff. ---------------------------------------------------------------
function onConnected(sync) {
	afterSaveRecheckReady()
}

// The Connect footer (Back + Connect & Finish) lives here, not inside
// LlmPoolEditor (:footerless), so it matches every other step's footer. Save
// is triggered on the editor via its exposed save() method.
const poolRef = ref(null)
const savingConnect = ref(false)
// True once the embedded editor reports a savable config (account connected,
// or API key filled) - gates the Connect & Finish button.
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
			// Advisory only (e.g. no Self-Host Tool User set yet) - the connection
			// itself is already saved, so this doesn't block the readiness recheck.
			if (m.warning) state.shWarning = m.warning
			await afterSaveRecheckReady()
		} else {
			state.shTestResult = m.result || {}
			state.shErr = "Validation failed. Fix the checks above, then retry."
		}
	} catch (e) {
		state.shSaveBusy = false
		state.shErr = errMsg(e)
	}
}

// Enter-step triggers: load the plan list on reaching "plan" (first entry
// from the tour, or a "Back" from selfhost/details), and probe dev-mode +
// preload Razorpay on reaching "pay".
watch(() => state.step, (s) => {
	if (s === "plan" && !state.plans.length && !state.plansLoading) {
		loadPlans().catch((e) => { state.plansErr = errMsg(e) })
	}
	if (s === "pay") enterPayStep()
})

// Prefill the Details step from what the site already knows (caller's email +
// default/sole company; options list for several) so the customer doesn't
// retype it. Backend-sourced because the SPA has no frappe.defaults. Never
// overwrites a value the user already typed; silent on any failure.
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
	--rad: 10px;
	font-family: 'Inter', system-ui, sans-serif;
	min-height: 100vh;
	background: var(--surface-1);
	color: var(--text);
	display: flex;
	flex-direction: column;
	position: relative;
}
/* Framing orbs - fixed behind everything, decorative only. Deep navy/indigo in
   light (consistent with the black/white primary), brighter blue on dark. */
.jv-ob-bg { position: fixed; inset: 0; z-index: 0; overflow: hidden; pointer-events: none; }
.jv-ob-orb { position: absolute; width: min(760px, 66vw); aspect-ratio: 1; border-radius: 50%; filter: blur(14px); }
.jv-ob-orb-tl { left: -180px; top: -170px; background: radial-gradient(circle, rgba(30, 58, 138, .24) 0%, transparent 62%); }
.jv-ob-orb-br { right: -190px; bottom: -190px; background: radial-gradient(circle, rgba(49, 46, 129, .20) 0%, transparent 62%); }
.jv-dark .jv-ob-orb-tl { background: radial-gradient(circle, rgba(59, 130, 246, .22) 0%, transparent 60%); }
.jv-dark .jv-ob-orb-br { background: radial-gradient(circle, rgba(99, 102, 241, .18) 0%, transparent 60%); }

.jv-ob-main { position: relative; z-index: 1; flex: 1; min-width: 0; overflow-y: auto; }
/* Fills the viewport so the card centers vertically when short; when a step is
   taller than the viewport it grows and the card top-aligns (scrolls from top,
   no cutoff). */
.jv-ob-center {
	min-height: 100%;
	box-sizing: border-box;
	display: flex;
	align-items: center;
	justify-content: center;
	padding: 26px 20px 60px;
}
.jv-ob-wrap { max-width: 1080px; width: 100%; display: flex; flex-direction: column; align-items: center; }

/* ---- brand header (preview .brand) ---- */
.jv-ob-brand { display: flex; align-items: center; gap: 10px; align-self: flex-start; margin-bottom: 8px; }
.jv-ob-logo {
	width: 30px; height: 30px; flex: none; border-radius: 8px;
	display: grid; place-items: center;
	background: linear-gradient(135deg, #6e8bff, #8b5cf6);
	box-shadow: 0 4px 14px rgba(110, 92, 246, .3);
}
.jv-ob-brand-name { font-size: 15px; font-weight: 600; letter-spacing: -.01em; }
.jv-ob-brand-sub { font-size: 12.5px; color: var(--text-3); border-left: 1px solid var(--border); padding-left: 11px; }

/* ---- step rail (preview .steps) ---- */
.jv-ob-steps { display: flex; align-items: center; margin: 16px 0 22px; width: 100%; max-width: 720px; }
.jv-ob-step { display: flex; align-items: center; gap: 8px; font-size: 12.5px; font-weight: 500; color: var(--text-3); white-space: nowrap; }
.jv-ob-step-dot {
	width: 22px; height: 22px; border-radius: 50%;
	display: grid; place-items: center;
	font-size: 11px; font-weight: 600; flex: none;
	border: 1.5px solid var(--border-2); background: var(--surface); color: var(--text-3);
}
.jv-ob-step.done .jv-ob-step-dot { background: var(--green-bg); border-color: var(--green-bd); color: var(--green); }
.jv-ob-step.active { color: var(--text); }
.jv-ob-step.active .jv-ob-step-dot { background: var(--blue); border-color: var(--blue); color: #fff; }
.jv-ob-step-line { flex: 1; height: 1.5px; background: var(--border); margin: 0 12px; min-width: 24px; }
.jv-ob-step-line.done { background: var(--green-bd); }

/* ---- panel + shared step body/foot (preview .panel/.body/.foot) ---- */
.jv-ob-panel {
	width: 100%;
	background: var(--surface);
	border: 1px solid var(--border);
	border-radius: 18px;
	box-shadow: 0 24px 70px rgba(20, 20, 30, .16);
	overflow: hidden;
}
.jv-dark .jv-ob-panel { box-shadow: 0 24px 70px rgba(0, 0, 0, .5); }
.jv-ob-screen { animation: jvObFade .25s ease; }
@keyframes jvObFade {
	from { opacity: 0; transform: translateY(6px); }
	to { opacity: 1; transform: none; }
}
/* min-height keeps every step's dialog the same size; shorter content
   top-aligns inside it. The tour matches at 624px (TourIntro.vue). */
.jv-ob-body { padding: 34px 40px 30px; min-height: 540px; box-sizing: border-box; }
.jv-ob-head { text-align: center; margin-bottom: 24px; }
.jv-ob-head h1 { font-size: 24px; font-weight: 660; letter-spacing: -.01em; margin: 0 0 7px; text-wrap: balance; }
.jv-ob-head p { font-size: 14px; color: var(--text-2); margin: 0; }
.jv-ob-foot {
	display: flex; align-items: center; justify-content: space-between; gap: 12px;
	padding: 18px 40px 26px; border-top: 1px solid var(--border);
}
.jv-ob-foot-end { justify-content: flex-end; }
.jv-ob-back { font-size: 13px; color: var(--text-2); background: none; border: none; cursor: pointer; font-family: inherit; display: inline-flex; align-items: center; gap: 6px; padding: 4px 2px; }
.jv-ob-back:hover { color: var(--text); }
.jv-ob-back:disabled { opacity: .5; cursor: default; }
/* quiet self-host link on the Plan footer */
.jv-ob-link { font-size: 12.5px; color: var(--text-3); background: none; border: none; cursor: pointer; font-family: inherit; text-decoration: underline; text-underline-offset: 3px; padding: 4px 2px; }
.jv-ob-link:hover { color: var(--text-2); }

/* keyboard focus. Text inputs are excluded: .jv-ob-inp:focus (and the combo's
   focus-within) already draw the preview's 3px ring, so the outline would
   double up. */
.jv-ob-root button:focus-visible,
.jv-ob-root input[type="checkbox"]:focus-visible,
.jv-ob-root [tabindex]:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }

/* ---- buttons: black/white system (--blue = near-black light / indigo dark).
   The ONLY gradient button in the flow is Connect & Finish. ---- */
.jv-ob-btn {
	display: inline-flex; align-items: center; justify-content: center; gap: 7px;
	height: 40px; padding: 0 20px; border-radius: 11px;
	border: 1px solid var(--border-2);
	font-family: inherit; font-size: 13.5px; font-weight: 600; line-height: 1;
	cursor: pointer; white-space: nowrap;
	background: var(--surface); color: var(--text-2);
	transition: transform .12s, box-shadow .15s, background .15s, border-color .15s;
}
.jv-ob-btn:hover { background: var(--surface-2); color: var(--text); border-color: var(--border); }
.jv-ob-btn:active { transform: scale(.98); }
.jv-ob-btn:disabled { opacity: .55; cursor: default; transform: none; }
.jv-ob-btn-primary { background: var(--blue); border-color: transparent; color: #fff; box-shadow: 0 2px 10px rgba(20, 20, 30, .16); }
.jv-ob-btn-primary:hover:not(:disabled) { background: var(--blue); color: #fff; transform: translateY(-1px); box-shadow: 0 8px 22px rgba(20, 20, 30, .22); }
.jv-ob-btn-grad { background: linear-gradient(135deg, #6e8bff, #8b5cf6); border-color: transparent; color: #fff; box-shadow: 0 6px 20px rgba(110, 92, 246, .32); }
.jv-ob-btn-grad:hover:not(:disabled) { color: #fff; transform: translateY(-1px); box-shadow: 0 10px 26px rgba(110, 92, 246, .4); }

.jv-ob-placeholder { font-size: 13.5px; color: var(--text-3); margin: 0 0 20px; text-align: center; }
.jv-ob-err { font-size: 12.5px; color: var(--red); min-height: 1em; margin: 10px 0 0; }
.jv-ob-err-center { text-align: center; }
.jv-ob-hint { font-size: 13px; color: var(--text-3); text-align: center; margin: 0; }

/* "Setting up" transition spinner (pay provisioning + connect finishing). */
.jv-ob-spinner { width: 34px; height: 34px; margin: 10px auto 0; border-radius: 50%; border: 3px solid var(--border-2); border-top-color: var(--blue); animation: jvObSpin .8s linear infinite; }
@keyframes jvObSpin { to { transform: rotate(360deg); } }

/* ---- Plan cards (preview .plans/.plan) ---- */
.jv-ob-plans { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.jv-ob-plan {
	border: 1.5px solid var(--border); border-radius: 14px; padding: 20px 18px;
	background: var(--surface); cursor: pointer; position: relative;
	transition: border-color .15s, box-shadow .15s, transform .15s;
}
.jv-ob-plan:hover { border-color: var(--border-2); transform: translateY(-2px); box-shadow: 0 10px 26px rgba(20, 20, 30, .08); }
.jv-ob-plan.sel { border-color: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-ob-plan-tag {
	position: absolute; top: -10px; left: 18px;
	font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em;
	color: var(--blue); background: var(--blue-bg); border: 1px solid var(--blue-bd);
	border-radius: 99px; padding: 3px 9px;
}
.jv-ob-plan-nm { font-size: 15px; font-weight: 600; }
.jv-ob-plan-pr { font-size: 26px; font-weight: 680; margin: 10px 0 2px; letter-spacing: -.02em; }
.jv-ob-plan-pr span { font-size: 13px; font-weight: 500; color: var(--text-3); letter-spacing: 0; }
.jv-ob-plan-cyc { font-size: 12px; color: var(--text-3); }
.jv-ob-plan ul { list-style: none; margin: 16px 0 0; padding: 0; display: grid; gap: 8px; }
.jv-ob-plan li { display: flex; gap: 8px; align-items: flex-start; font-size: 12.5px; color: var(--text-2); }
.jv-ob-plan li svg { color: var(--green); flex: none; margin-top: 1px; }
.jv-ob-plan-rd {
	position: absolute; top: 18px; right: 18px;
	width: 18px; height: 18px; border-radius: 50%;
	border: 1.5px solid var(--border-2); display: grid; place-items: center;
}
.jv-ob-plan.sel .jv-ob-plan-rd { border-color: var(--blue); background: var(--blue); }
.jv-ob-plan.sel .jv-ob-plan-rd::after { content: ""; width: 7px; height: 7px; border-radius: 50%; background: #fff; }
.jv-ob-muted { color: var(--text-3); }

/* ---- Details form (preview .form/.field/.sec-label) ---- */
.jv-ob-form { display: grid; grid-template-columns: 1fr 1fr; gap: 16px 18px; max-width: 620px; margin: 0 auto; }
.jv-ob-field { display: flex; flex-direction: column; gap: 6px; }
.jv-ob-field-full { grid-column: 1 / -1; }
.jv-ob-field label { font-size: 12.5px; font-weight: 550; color: var(--text-2); }
.jv-ob-opt { color: var(--text-3); font-weight: 400; }
.jv-ob-inp {
	height: 42px; border: 1px solid var(--border-2); border-radius: 10px;
	background: var(--surface); padding: 0 13px;
	font-family: inherit; font-size: 13.5px; color: var(--text);
	width: 100%; box-sizing: border-box;
}
.jv-ob-inp::placeholder { color: var(--text-3); }
.jv-ob-inp:focus { outline: none; border-color: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-ob-sec-label {
	grid-column: 1 / -1;
	font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em;
	color: var(--text-3); margin: 6px 0 -4px;
}
/* JvCombo (Company) restyled to match the preview's .inp fields: 42px, 10px
   radius, border-2 border, and the same 3px focus ring (focus-within because
   the ring belongs on the wrapper, the caret sits in the inner input). */
.jv-ob-form :deep(.jvc-field) {
	min-height: 42px; padding: 0 13px; gap: 8px;
	border-color: var(--border-2); border-radius: 10px;
	font-size: 13.5px;
	transition: border-color .15s, box-shadow .15s;
}
.jv-ob-form :deep(.jvc-field:hover) { border-color: var(--border-2); }
.jv-ob-form :deep(.jvc-field:focus-within),
.jv-ob-form :deep(.jvc-field.jvc-open) { border-color: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-ob-form :deep(.jvc-input::placeholder) { color: var(--text-3); }

/* ---- Review & Pay (preview .rev) ---- */
.jv-ob-rev { max-width: 560px; margin: 0 auto; border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
.jv-ob-rev-row { display: flex; justify-content: space-between; gap: 12px; padding: 13px 18px; font-size: 13.5px; border-bottom: 1px solid var(--border); }
.jv-ob-rev-row:last-child { border-bottom: 0; }
.jv-ob-rev-row span { color: var(--text-3); }
.jv-ob-rev-row b { font-weight: 600; }
.jv-ob-rev-total { background: var(--surface-1); font-size: 15px; }
.jv-ob-rev-total b { font-size: 17px; }
.jv-ob-rev-note { max-width: 560px; margin: 14px auto 0; font-size: 12px; color: var(--text-3); text-align: center; display: flex; align-items: center; justify-content: center; gap: 7px; }
.jv-ob-devnote { font-size: 12.5px; color: var(--amber); background: var(--amber-bg); border: 1px solid var(--amber-bd); border-radius: 8px; padding: 8px 12px; margin: 14px auto 0; max-width: 560px; }

/* ---- Connect ---- */
.jv-ob-connect { max-width: 640px; margin: 0 auto; }

/* ---- Self-host (logic unchanged; light restyle to the new frame) ---- */
.jv-ob-sh { max-width: 620px; margin: 0 auto; }
.jv-ob-label { display: block; font-size: 12.5px; font-weight: 550; color: var(--text-2); margin: 14px 0 6px; }
.jv-ob-sh .jv-ob-label:first-of-type { margin-top: 0; }
.jv-ob-check { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text); margin-top: 10px; cursor: pointer; }
.jv-ob-sh-actions { display: flex; margin-top: 14px; }
.jv-ob-sh-results { margin: 14px 0 4px; font-size: 12.5px; line-height: 1.7; }
.jv-ob-sh-check { color: var(--text); }
.jv-ob-sh-check-adv { color: var(--text-3); }
.jv-ob-sh-adv-tag { color: var(--text-3); font-style: italic; }
.jv-ob-sh-ok { color: var(--green); font-weight: 600; margin-bottom: 4px; }
.jv-ob-sh-bad { color: var(--red); font-weight: 600; margin-bottom: 4px; }

/* ---- Connect / self-host post-save readiness note (afterSaveRecheckReady). ---- */
.jv-ob-note { font-size: 12.5px; color: var(--text-3); margin-top: 14px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: center; }

@media (max-width: 820px) {
	.jv-ob-body { min-height: 0; padding: 26px 22px 22px; }
	.jv-ob-foot { padding: 14px 22px 20px; }
	.jv-ob-plans { grid-template-columns: 1fr; }
	.jv-ob-form { grid-template-columns: 1fr; }
	.jv-ob-orb { width: min(520px, 90vw); }
	.jv-ob-head h1 { font-size: 21px; }
	.jv-ob-foot { flex-wrap: wrap; }
}
@media (prefers-reduced-motion: reduce) {
	.jv-ob-screen { animation: none; }
	.jv-ob-plan, .jv-ob-btn, .jv-ob-form :deep(.jvc-field) { transition: none; }
	.jv-ob-spinner { animation: none; }
}
</style>
