<template>
	<div class="jv-ob-root" :class="{ 'jv-dark': dark }" :style="paletteVars">

		<main class="jv-ob-main">
			<div class="jv-ob-center">
				<div class="jv-ob-wrap">

					<!-- brand header: JarvisMark + name + per-step subtitle (preview .brand) -->
					<div class="jv-ob-brand">
						<JarvisMark :size="30" :radius="8" />
						<span class="jv-ob-brand-name">Jarvis</span>
						<span class="jv-ob-brand-sub">{{ frameSub }}</span>
					</div>

				<!-- step rail: flat progress segments with labels (design.md §4.3 —
					 no numbered circles, no connector lines). Hidden on the intro
					 tour (chromeless) and on the single-step self-host track. -->
				<div v-if="railIndex >= 0" class="jv-ob-steps" role="list" aria-label="Setup steps">
					<div v-for="(s, i) in RAIL" :key="s.id" role="listitem" class="jv-ob-step"
						 :class="{ done: i < railIndex, active: i === railIndex }"
						 :aria-current="i === railIndex ? 'step' : undefined">
						<span class="jv-ob-step-label">{{ s.label }}</span>
						<span class="jv-ob-step-bar"></span>
					</div>
				</div>

					<div class="jv-ob-panel">

						<!-- ===== Intro tour (fresh starts only; reconcile routes mid-flight
							 signups straight to the right step, past the tour) ===== -->
						<TourIntro v-if="state.step === 'intro'" @finish="startWizard" @skip="startWizard" />

						<!-- ===== Choose Your Plan ===== -->
						<section v-else-if="state.step === 'plan'" class="jv-ob-screen">
							<div class="jv-ob-body">
								<div class="jv-ob-head">
									<h1>Choose your plan</h1>
									<p>Start free. Upgrade or extend anytime, with no auto-renewal.</p>
								</div>
								<div v-if="state.plansLoading" class="jv-ob-placeholder">Loading plans…</div>
								<Banner v-else-if="state.plansErr" type="error" :message="state.plansErr">
									<template #action>
										<button class="jv-ob-btn jv-ob-btn-sm" @click="loadPlansSafe">Retry</button>
									</template>
								</Banner>
								<div v-else-if="!state.plans.length" class="jv-ob-placeholder">No plans are available right now. Please contact support.</div>
								<div v-else class="jv-ob-plans" role="radiogroup" aria-label="Plan">
									<div v-for="p in state.plans" :key="p.name" class="jv-ob-plan"
										 :class="{ sel: state.planName === p.name }" role="radio"
										 :aria-checked="state.planName === p.name" tabindex="0"
										 @click="state.planName = p.name"
										 @keydown.enter.prevent="state.planName = p.name"
										 @keydown.space.prevent="state.planName = p.name">
										<div class="jv-ob-plan-rd"></div>
										<div class="jv-ob-plan-nm">{{ p.plan_name }}</div>
										<div class="jv-ob-plan-pr">{{ planAmount(p.price_inr) }}<span v-if="planSuffix(p.price_inr, p.billing_cycle)"> {{ planSuffix(p.price_inr, p.billing_cycle) }}</span></div>
										<div class="jv-ob-plan-cyc">{{ planCycleLabel(p) }}</div>
										<ul>
											<li v-for="(f, k) in planFeatures(p)" :key="k"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>{{ f }}</li>
											<li v-if="!planFeatures(p).length" class="jv-ob-muted">{{ p.billing_cycle }} plan</li>
										</ul>
									</div>
								</div>
							</div>
							<div class="jv-ob-foot">
								<button class="jv-ob-back" @click="goBack"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>Back to tour</button>
								<button class="jv-ob-link" @click="enterSelfhost">Self-hosted? Connect your own openclaw</button>
								<button class="jv-ob-btn jv-ob-btn-primary" :disabled="!state.planName" @click="onPlanContinue">Continue</button>
							</div>
						</section>

						<!-- ===== Your Details ===== -->
						<section v-else-if="state.step === 'details'" class="jv-ob-screen">
							<div class="jv-ob-body">
								<div class="jv-ob-head">
									<h1>Your details</h1>
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
										<label for="jv-ob-contact">Contact number <span class="jv-ob-opt">(optional)</span></label>
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
									<div class="jv-ob-sec-hint">Billing details are kept with your account for upcoming invoicing.</div>
									<div class="jv-ob-field jv-ob-field-full">
										<label for="jv-ob-addr">Billing address <span class="jv-ob-opt">(optional)</span></label>
										<input id="jv-ob-addr" class="jv-ob-inp" type="text" v-model="state.billingAddress"
											   placeholder="Street, area" autocomplete="street-address"
											   @keydown.enter="onDetailsSubmit">
									</div>
									<div class="jv-ob-field">
										<label for="jv-ob-city">City <span class="jv-ob-opt">(optional)</span></label>
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
								<Banner v-if="state.detailsErr" type="error" :message="state.detailsErr" role="alert" aria-live="polite" />
							</div>
							<div class="jv-ob-foot">
								<button class="jv-ob-back" @click="goBack"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>Back</button>
								<button class="jv-ob-btn jv-ob-btn-primary" @click="onDetailsSubmit">Continue</button>
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
									<Banner v-if="state.provisionErr" type="error" :message="state.provisionErr" role="alert" />
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
									<Banner v-if="state.payErr" type="error" :message="state.payErr" />
								</div>
								<div class="jv-ob-foot jv-ob-foot-end">
									<button class="jv-ob-btn jv-ob-btn-primary" :disabled="state.payBusy" @click="onVerifyCheck">
										{{ state.payBusy ? "Working…" : "I've verified my email" }}
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
									<button class="jv-ob-btn jv-ob-btn-primary" @click="goNext">Continue</button>
								</div>
							</template>
							<template v-else>
								<div class="jv-ob-body">
									<div class="jv-ob-head">
										<h1>Review &amp; pay</h1>
										<p>{{ isFreePlan ? "Confirm the details below." : "Confirm the details below. You'll complete payment securely via Razorpay." }}</p>
									</div>
									<div class="jv-ob-rev">
										<div class="jv-ob-rev-row"><span>Plan</span><b>{{ planRowLabel }}</b></div>
										<div class="jv-ob-rev-row"><span>Company</span><b>{{ state.company }}</b></div>
										<div class="jv-ob-rev-row"><span>Billed to</span><b>{{ state.email }}</b></div>
										<div class="jv-ob-rev-row jv-ob-rev-total"><span>Due today</span><b>{{ dueTodayLabel }}</b></div>
									</div>
									<div v-if="!isFreePlan" class="jv-ob-rev-note">
										<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>
										Secured by Razorpay · cards, UPI &amp; netbanking
									</div>
									<div v-if="state.devActive" class="jv-ob-devnote">Developer mode: payment is skipped (dev signup).</div>
									<Banner v-if="state.payErr" type="error" :message="state.payErr" />
								</div>
								<div class="jv-ob-foot">
									<button class="jv-ob-back" :disabled="state.payBusy" @click="goBack"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>Back</button>
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
									<div class="jv-ob-setup-net">
										<SetupNeuralNet :dark="dark" />
									</div>
								</div>
								<div v-show="!state.finishing">
									<div class="jv-ob-head">
										<h1>Give Jarvis a brain</h1>
										<p>Pick which AI powers Jarvis. You can change this anytime in Settings → AI models.</p>
									</div>
									<div class="jv-ob-connect">
										<LlmPoolEditor ref="poolRef" :editable="true" :modes="['quick']" :footerless="true" @saved="onConnected" @ready="connectReady = $event" />
									</div>
									<Banner v-if="state.finishNote" type="info" :message="state.finishNote">
										<template #action>
											<button class="jv-ob-btn jv-ob-btn-primary" @click="forceContinue">Continue to Jarvis</button>
										</template>
									</Banner>
								</div>
							</div>
							<div v-if="!state.finishing" class="jv-ob-foot">
								<!-- No Back on a reconciled resume: signup/payment already completed
									 in a previous session, so there is no local pay/review context to
									 go back to (re-running startSignup there would double-sign-up). -->
								<button v-if="!state.reconciledConnect" class="jv-ob-back" :disabled="savingConnect" @click="goBack"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>Back</button>
								<span v-else></span>
								<!-- Always rendered; disabled until the editor reports a savable config,
									 so the step never shows without a primary action. -->
								<button class="jv-ob-btn jv-ob-btn-grad" :disabled="!connectReady || savingConnect" @click="saveConnect">
									{{ savingConnect ? "Connecting…" : "Start chatting" }}
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
							<svg v-if="c.ok" class="jv-ob-sh-ic jv-ob-sh-ic-ok" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="m9 12 2 2 4-4" /></svg>
							<svg v-else-if="c.advisory" class="jv-ob-sh-ic jv-ob-sh-ic-adv" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h16.9a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></svg>
							<svg v-else class="jv-ob-sh-ic jv-ob-sh-ic-bad" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="m15 9-6 6M9 9l6 6" /></svg>
							<span><b>{{ c.check }}</b> · {{ c.detail || "" }}<span v-if="c.advisory" class="jv-ob-sh-adv-tag"> · advisory</span></span>
						</div>
									</div>
									<Banner v-if="state.shWarning" type="warning" :message="state.shWarning" />
									<Banner v-if="state.shErr" type="error" :message="state.shErr" role="alert" aria-live="polite" />
									<div v-if="state.finishing" class="jv-ob-note">Finishing setup…</div>
									<Banner v-else-if="state.finishNote" type="info" :message="state.finishNote">
										<template #action>
											<button class="jv-ob-btn jv-ob-btn-primary" @click="forceContinue">Continue to Jarvis</button>
										</template>
									</Banner>
								</div>
							</div>
							<div class="jv-ob-foot">
								<!-- Stay disabled through the post-save readiness poll (finishing) too;
									 both flags drop on the failure paths so retry stays possible. -->
								<button class="jv-ob-back" :disabled="state.shSaveBusy || state.finishing" @click="backFromSelfhost"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6" /></svg>Back</button>
								<button class="jv-ob-btn jv-ob-btn-primary" :disabled="state.shSaveBusy || state.finishing" @click="onSelfHostSave">
									{{ state.shSaveBusy || state.finishing ? "Connecting…" : "Connect" }}
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
import JarvisMark from "@/components/JarvisMark.vue"
import Banner from "@/components/Banner.vue"
import TourIntro from "@/onboarding/TourIntro.vue"
import SetupNeuralNet from "@/onboarding/SetupNeuralNet.vue"
import { STEPS_MANAGED, STEPS_SELFHOST, nextStep, prevStep } from "@/onboarding/steps"
import { inr, planAmount, planSuffix } from "@/account/format"
import {
	checkSignupPaymentState, isReadyForChat, getLlmSyncStatus,
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
	plan: "Choose your plan",
	details: "Your details",
	pay: "Review & pay",
	connect: "Give Jarvis a brain",
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
	// True when reconcile landed us directly on "connect" (signup + payment
	// completed in an earlier session): there is no local plan/email/company
	// context, so Back to Review & Pay is hidden (it would re-run start_signup
	// with empty args).
	reconciledConnect: false,
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

// No "Popular" tag: the admin plan catalog carries no recommended/popular
// flag, and fabricating one positionally (e.g. always the middle card) would
// mislabel whatever plan happens to sit there. Reintroduce only if the
// catalog grows a real flag.

// Free-plan detection drives the Review & Pay copy: no Razorpay promise, no
// lock note, "Free" in the total row.
const isFreePlan = computed(() => (Number(selectedPlan.value.price_inr) || 0) <= 0)

// Pay CTA copy: dev signup in sandbox; "Pay ₹X →" for a paid plan; plain
// sign-up for a free one.
const payCta = computed(() => {
	if (state.devActive) return "Dev signup & connect"
	return isFreePlan.value ? "Sign up" : `Pay ${inr(selectedPlan.value.price_inr)}`
})

// Review-card labels (preview .rev): "Pro · Monthly" plan row and a plain
// amount in the emphasized total row.
const planRowLabel = computed(() => {
	const p = selectedPlan.value
	if (!p.plan_name) return ""
	return p.billing_cycle ? `${p.plan_name} · ${p.billing_cycle}` : p.plan_name
})
const dueTodayLabel = computed(() => planAmount(selectedPlan.value.price_inr))

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
		if (ready && (ready.reason === "llm_credentials" || ready.reason === "llm_pool_provisioning")) {
			// Signup + payment already done; only the AI connection is missing
			// (llm_credentials) or a configured pool never finished its first
			// apply (llm_pool_provisioning) - both resume at the connect step,
			// whose sync-status poller shows the pending/failed state. Mark the
			// resume so the Connect step hides Back (no local signup context to
			// return to - see state.reconciledConnect).
			state.mode = "managed"
			state.step = "connect"
			state.reconciledConnect = true
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
// Error-surfacing wrapper shared by the step-entry watch, the Retry button on
// a failed load, and the intro-tour prefetch.
function loadPlansSafe() {
	loadPlans().catch((e) => { state.plansErr = errMsg(e) })
}
// Feature list parsing matches desk's renderPlan card body verbatim.
function planFeatures(p) {
	return String((p && p.features) || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean)
}
// The price renders as a big amount with a small muted "/mo" suffix
// (₹3,999 <span>/mo</span>) via the shared planAmount/planSuffix helpers
// from account/format.js (same semantics as planPriceLabel there).
// Cycle line under the price, per the approved preview copy ("Billed monthly"
// on paid cards, "For trying Jarvis" on the free one). Copy-only, but keyed
// off the shared suffix helper so the cycle rule can't drift.
function planCycleLabel(p) {
	const suffix = planSuffix(p && p.price_inr, p && p.billing_cycle)
	if (!suffix) return "For trying Jarvis"
	return suffix === "/yr" ? "Billed annually" : "Billed monthly"
}
function onPlanContinue() {
	if (!state.planName) return
	goNext()
}

// ---- Details (Your Details) -------------------------------------------------
// Validation matches the old Account step verbatim: email regex + non-empty
// company. The contact/billing fields are collected but not (yet) submitted -
// see the TODO(backend) note on `state` above. Until the backend accepts
// them, they're persisted to localStorage on submit so they survive reloads
// and can be backfilled once the signup contract carries them.
const BILLING_LS_KEY = "jarvis-onboarding-billing"
function persistBillingDetails() {
	try {
		window.localStorage.setItem(BILLING_LS_KEY, JSON.stringify({
			contact: state.contact, billingAddress: state.billingAddress,
			city: state.city, gstin: state.gstin,
		}))
	} catch (e) { /* storage full/blocked - purely best-effort */ }
}
// Restore on mount; never overwrites something the user already typed.
function restoreBillingDetails() {
	try {
		const d = JSON.parse(window.localStorage.getItem(BILLING_LS_KEY) || "{}")
		if (d.contact && !state.contact) state.contact = d.contact
		if (d.billingAddress && !state.billingAddress) state.billingAddress = d.billingAddress
		if (d.city && !state.city) state.city = d.city
		if (d.gstin && !state.gstin) state.gstin = d.gstin
	} catch (e) { /* corrupt entry - ignore */ }
}
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
	persistBillingDetails()
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
	// Guard against a signup with empty args: on a reconciled resume (or any
	// state loss) there is no local plan/email/company, and startSignup(email,
	// company, null) would create a broken signup upstream.
	if (!state.planName || !state.email || !state.company) {
		state.payErr = "Your signup details are missing. Please go back and pick a plan and enter your details again."
		return
	}
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

// First-time provisioning runs in a background job whose budget is minutes
// (cold container provision + proxy sidecars), not seconds. Readiness only
// flips once that job APPLIES the pool, so before probing is_ready_for_chat
// we follow the job itself: poll get_llm_sync_status until it leaves
// "pending:". The ceiling is a UX bound, not a correctness guarantee: it
// clears the backend's 600s job envelope (ADMIN_SYNC_RQ_TIMEOUT_S) plus one
// lock-loss retry hop; a pathological retry chain can honestly outlast it,
// in which case the caller falls through to the "still finishing" note with
// a manual continue - never a hard block. Returns the terminal sync dict,
// or null on timeout.
async function waitForSyncTerminal(maxMs = 15 * 60 * 1000, intervalMs = 3000) {
	const deadline = Date.now() + maxMs
	for (;;) {
		try {
			const s = await getLlmSyncStatus()
			if (s && !s.pending) return s
		} catch (e) {
			// transient network hiccups shouldn't strand the user
		}
		if (Date.now() >= deadline) return null
		await sleep(intervalMs)
	}
}

// Shared tail for both completion paths: optionally follow an in-flight
// provisioning sync to a terminal state, then poll for readiness, then
// either auto-reload (the common case) or leave a "still finishing" note
// with a manual continue button so the user is never stuck on a spinner.
//
// followSync is ONLY for the managed pool path (save_llm_pool writes a
// "pending:" status synchronously before returning, so a sync from THIS
// save is observable as pending right now). The self-host save never
// touches last_sync_status, and a no-op / container-owned managed save
// enqueues nothing - in both cases the field may hold a STALE terminal
// "failed:" (or a stale "pending:" from an abandoned earlier attempt),
// which must not block an actually-ready tenant. Hence: only follow a
// sync we can see in flight, and never gate the self-host path on this
// field at all.
async function afterSaveRecheckReady({ followSync = false } = {}) {
	state.finishNote = ""
	state.finishing = true
	if (followSync) {
		// save_llm_pool writes "pending:" synchronously before its response,
		// and onConnected only fires after a successful save - so whatever
		// this probe reads is THIS save's sync: still pending (follow it to
		// terminal) or already terminal (a fast failure, e.g. an immediate
		// auth error - which must surface its actionable status, not fall
		// through to a generic "still finishing" note that hides the
		// diagnostic the status field already carries).
		let terminal = null
		try {
			const s0 = await getLlmSyncStatus()
			terminal = s0 && s0.pending ? await waitForSyncTerminal() : s0
		} catch (e) {
			// status probe is advisory - fall through to the readiness poll
		}
		const status = ((terminal && terminal.last_sync_status) || "").trim()
		if (status.startsWith("failed") || status.startsWith("skipped")) {
			state.finishing = false
			state.finishNote = `Setup hit a problem (${status}). Check the AI connection and save again - or continue to Jarvis and retry from Settings.`
			return
		}
	}
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
	afterSaveRecheckReady({ followSync: true })
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
		loadPlansSafe()
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

onMounted(async () => {
	prefillAccount()
	restoreBillingDetails()
	await reconcileMidFlightSignup()
	// Prefetch the plan catalog behind the intro tour so the Plan step rarely
	// first-paints in its loading state. Reconciled resumes land past "plan"
	// and skip it (the step-entry watch still covers every other path).
	if (state.step === "intro" && !state.plans.length && !state.plansLoading) loadPlansSafe()
})
</script>

<style scoped>
/* Styling follows design.md (§4.3 onboarding & wizards): flat neutral surfaces,
   near-black solid CTAs, colour-shift-only hover, no decorative motion. */
.jv-ob-root {
	--rad: 8px;
	min-height: 100vh;
	background: var(--surface-1);
	color: var(--text);
	display: flex;
	flex-direction: column;
	position: relative;
}

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

/* ---- brand header: the mark is the one sanctioned brand asset (design.md
   §2.2); no glow shadow around it. ---- */
.jv-ob-brand { display: flex; align-items: center; justify-content: center; gap: 10px; align-self: center; margin-bottom: 8px; }
.jv-ob-brand-name { font-size: 15px; font-weight: 600; }
.jv-ob-brand-sub { font-size: 13px; color: var(--text-3); border-left: 1px solid var(--border); padding-left: 11px; }

/* ---- step rail: labelled flat segments (design.md §4.3) ---- */
.jv-ob-steps { display: flex; align-items: stretch; gap: 8px; margin: 16px 0 22px; width: 100%; max-width: 720px; }
.jv-ob-step { flex: 1; display: flex; flex-direction: column; gap: 6px; }
.jv-ob-step-label { font-size: 12.5px; font-weight: 420; color: var(--text-3); }
.jv-ob-step.active .jv-ob-step-label { color: var(--text); font-weight: 500; }
.jv-ob-step.done .jv-ob-step-label { color: var(--text-2); }
.jv-ob-step-bar { height: 4px; border-radius: 999px; background: var(--surface-3); }
.jv-ob-step.done .jv-ob-step-bar, .jv-ob-step.active .jv-ob-step-bar { background: var(--text); }

/* ---- panel + shared step body/foot ---- */
.jv-ob-panel {
	width: 100%;
	background: var(--surface);
	border: 1px solid var(--border);
	border-radius: 16px;
	box-shadow: 0 0 1px rgba(0, 0, 0, .2), 0 24px 30px -8px rgba(0, 0, 0, .1);
	overflow: hidden;
}
.jv-ob-screen { animation: jvObFade .15s ease-out; }
@keyframes jvObFade {
	from { opacity: 0; }
	to { opacity: 1; }
}
/* min-height keeps every step's dialog the same size; shorter content
   top-aligns inside it. The tour matches at 604px (TourIntro.vue). */
.jv-ob-body { padding: 32px 40px 28px; min-height: 520px; box-sizing: border-box; }
.jv-ob-head { text-align: center; margin-bottom: 24px; }
.jv-ob-head h1 { font-size: 20px; font-weight: 600; margin: 0 0 7px; text-wrap: balance; }
.jv-ob-head p { font-size: 14px; line-height: 1.5; color: var(--text-2); margin: 0; }
.jv-ob-foot {
	display: flex; align-items: center; justify-content: space-between; gap: 12px;
	padding: 16px 40px 22px; border-top: 1px solid var(--border);
}
.jv-ob-foot-end { justify-content: flex-end; }
.jv-ob-back { font-size: 13px; font-weight: 420; color: var(--text-2); background: none; border: none; cursor: pointer; font-family: inherit; display: inline-flex; align-items: center; gap: 4px; padding: 6px 8px; border-radius: 8px; transition: background-color .15s ease, color .15s ease; }
.jv-ob-back svg { flex: none; color: var(--text-3); }
.jv-ob-back:hover { color: var(--text); background: var(--surface-2); }
.jv-ob-back:disabled { opacity: .5; cursor: default; }
/* quiet self-host link on the Plan footer — links look like links */
.jv-ob-link { font-size: 12.5px; color: var(--text-3); background: none; border: none; cursor: pointer; font-family: inherit; text-decoration: underline; text-underline-offset: 3px; padding: 4px 2px; }
.jv-ob-link:hover { color: var(--text-2); }

/* keyboard focus (text inputs draw their own focus border) */
.jv-ob-root button:focus-visible,
.jv-ob-root input[type="checkbox"]:focus-visible,
.jv-ob-root [tabindex]:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }

/* ---- buttons (design.md §3.1): solid near-black primary, subtle secondary,
   colour-shift hover only. The finishing CTA (.jv-ob-btn-grad class name kept
   for the template) is the same solid primary as everywhere else. ---- */
.jv-ob-btn {
	display: inline-flex; align-items: center; justify-content: center; gap: 7px;
	height: 36px; padding: 0 16px; border-radius: 8px;
	border: 1px solid transparent;
	font-family: inherit; font-size: 13.5px; font-weight: 500; line-height: 1;
	cursor: pointer; white-space: nowrap;
	background: var(--surface-2); color: var(--text);
	transition: background-color .15s ease, color .15s ease, border-color .15s ease;
}
/* :not(:disabled) is REQUIRED here. Without it this rule (specificity 0,2,0)
   outranks .jv-ob-btn-grad/.jv-ob-btn-primary (0,1,0) on hover, repainting a
   DISABLED primary button's background to near-white --surface-3 while its
   color stays var(--surface) (white) -> white-on-white, the button vanishes
   under the cursor. Hit live on the Connect step's "Start chatting" while it
   was still disabled. */
.jv-ob-btn:hover:not(:disabled) { background: var(--surface-3); }
.jv-ob-btn:disabled { opacity: .5; cursor: default; }
.jv-ob-btn-primary, .jv-ob-btn-grad { background: var(--text); border-color: var(--text); color: var(--surface); }
.jv-ob-btn-primary:hover:not(:disabled), .jv-ob-btn-grad:hover:not(:disabled) { background: var(--text-2); border-color: var(--text-2); color: var(--surface); }
/* small variant (inline Retry next to an error message) */
.jv-ob-btn-sm { height: 28px; padding: 0 12px; font-size: 12.5px; border-radius: 8px; margin-left: 8px; }

.jv-ob-placeholder { font-size: 13.5px; color: var(--text-3); margin: 0 0 20px; text-align: center; }
.jv-ob-err { font-size: 12.5px; color: var(--red); min-height: 1em; margin: 10px 0 0; }
.jv-ob-err-center { text-align: center; }
.jv-ob-hint { font-size: 13px; line-height: 1.5; color: var(--text-3); text-align: center; margin: 0; }

/* "Setting up" transition spinner (pay provisioning only - the connect
   finishing state uses the neural-net animation below). */
.jv-ob-spinner { width: 32px; height: 32px; margin: 10px auto 0; border-radius: 50%; border: 3px solid var(--surface-3); border-top-color: var(--text); animation: jvObSpin .8s linear infinite; }
@keyframes jvObSpin { to { transform: rotate(360deg); } }

/* "Setting up Jarvis" finishing state: neural-net animation replacing the
   spinner. Needs real height for the canvas to render into. */
.jv-ob-setup-net { position: relative; width: 100%; min-height: 380px; flex: 1; margin-top: 8px; }

/* ---- Plan cards: selectable radio cards; selection is a dark ring, hover is
   a background tint — never motion (design.md §4.2). ---- */
.jv-ob-plans { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.jv-ob-plan {
	border: 1px solid var(--border); border-radius: 10px; padding: 18px;
	background: var(--surface); cursor: pointer; position: relative;
	transition: border-color .15s ease, background-color .15s ease, box-shadow .15s ease;
}
.jv-ob-plan:hover { background: var(--surface-1); border-color: var(--border-2); }
.jv-ob-plan.sel { border-color: var(--text); box-shadow: 0 0 0 1px var(--text); }
.jv-ob-plan-nm { font-size: 14px; font-weight: 500; }
.jv-ob-plan-pr { font-size: 22px; font-weight: 500; margin: 10px 0 2px; }
.jv-ob-plan-pr span { font-size: 13px; font-weight: 420; color: var(--text-3); }
.jv-ob-plan-cyc { font-size: 12.5px; color: var(--text-3); }
.jv-ob-plan ul { list-style: none; margin: 14px 0 0; padding: 0; display: grid; gap: 8px; }
.jv-ob-plan li { display: flex; gap: 8px; align-items: flex-start; font-size: 13px; line-height: 1.4; color: var(--text-2); }
.jv-ob-plan li svg { color: var(--green); flex: none; margin-top: 1px; }
.jv-ob-plan-rd {
	position: absolute; top: 16px; right: 16px;
	width: 16px; height: 16px; border-radius: 50%;
	border: 1px solid var(--border-2); display: grid; place-items: center;
	transition: border-color .15s ease, background-color .15s ease;
}
.jv-ob-plan.sel .jv-ob-plan-rd { border-color: var(--text); background: var(--text); }
.jv-ob-plan.sel .jv-ob-plan-rd::after { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--surface); }
.jv-ob-muted { color: var(--text-3); }

/* ---- Details form (design.md §3.4 mapped to the page context) ---- */
.jv-ob-form { display: grid; grid-template-columns: 1fr 1fr; gap: 14px 16px; max-width: 620px; margin: 0 auto; }
.jv-ob-field { display: flex; flex-direction: column; gap: 6px; }
.jv-ob-field-full { grid-column: 1 / -1; }
.jv-ob-field label { font-size: 12px; font-weight: 420; color: var(--text-3); }
.jv-ob-opt { color: var(--text-3); font-weight: 420; }
.jv-ob-inp {
	height: 32px; border: 1px solid var(--border-2); border-radius: 8px;
	background: var(--surface); padding: 0 10px;
	font-family: inherit; font-size: 13.5px; color: var(--text);
	width: 100%; box-sizing: border-box;
	transition: border-color .15s ease, box-shadow .15s ease;
}
.jv-ob-inp::placeholder { color: var(--text-3); }
.jv-ob-inp:hover { border-color: var(--text-3); }
.jv-ob-inp:focus { outline: none; border-color: var(--text); box-shadow: 0 0 0 3px var(--surface-2); }
.jv-ob-sec-label {
	grid-column: 1 / -1;
	font-size: 14px; font-weight: 600;
	color: var(--text); margin: 8px 0 -4px;
}
.jv-ob-sec-hint { grid-column: 1 / -1; font-size: 12px; line-height: 1.5; color: var(--text-3); margin: 0 0 -6px; }
/* JvCombo (Company) matched to the input recipe above (focus-within because
   the border belongs on the wrapper, the caret sits in the inner input). */
.jv-ob-form :deep(.jvc-field) {
	min-height: 32px; padding: 0 10px; gap: 8px;
	border-color: var(--border-2); border-radius: 8px;
	font-size: 13.5px;
	transition: border-color .15s ease, box-shadow .15s ease;
}
.jv-ob-form :deep(.jvc-field:hover) { border-color: var(--text-3); }
.jv-ob-form :deep(.jvc-field:focus-within),
.jv-ob-form :deep(.jvc-field.jvc-open) { border-color: var(--text); box-shadow: 0 0 0 3px var(--surface-2); }
.jv-ob-form :deep(.jvc-input::placeholder) { color: var(--text-3); }

/* ---- Review & pay ---- */
.jv-ob-rev { max-width: 560px; margin: 0 auto; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.jv-ob-rev-row { display: flex; justify-content: space-between; gap: 12px; padding: 12px 16px; font-size: 13.5px; border-bottom: 1px solid var(--border); }
.jv-ob-rev-row:last-child { border-bottom: 0; }
.jv-ob-rev-row span { color: var(--text-3); }
.jv-ob-rev-row b { font-weight: 500; }
.jv-ob-rev-total { background: var(--surface-1); }
.jv-ob-rev-total b { font-size: 15px; font-weight: 600; }
.jv-ob-rev-note { max-width: 560px; margin: 14px auto 0; font-size: 12px; color: var(--text-3); text-align: center; display: flex; align-items: center; justify-content: center; gap: 7px; }
.jv-ob-devnote { font-size: 12.5px; color: var(--amber); background: var(--amber-bg); border: 1px solid var(--amber-bd); border-radius: 8px; padding: 8px 12px; margin: 14px auto 0; max-width: 560px; }

/* ---- Connect ---- */
.jv-ob-connect { max-width: 640px; margin: 0 auto; }

/* ---- Self-host (logic unchanged) ---- */
.jv-ob-sh { max-width: 620px; margin: 0 auto; }
.jv-ob-label { display: block; font-size: 12px; font-weight: 420; color: var(--text-3); margin: 14px 0 6px; }
.jv-ob-sh .jv-ob-label:first-of-type { margin-top: 0; }
.jv-ob-check { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text); margin-top: 10px; cursor: pointer; }
.jv-ob-sh-actions { display: flex; margin-top: 14px; }
.jv-ob-sh-results { margin: 14px 0 4px; font-size: 12.5px; line-height: 1.6; }
.jv-ob-sh-check { display: flex; align-items: flex-start; gap: 7px; color: var(--text); padding: 2px 0; }
.jv-ob-sh-check-adv { color: var(--text-3); }
.jv-ob-sh-ic { flex: none; margin-top: 2px; }
.jv-ob-sh-ic-ok { color: var(--green); }
.jv-ob-sh-ic-adv { color: var(--amber); }
.jv-ob-sh-ic-bad { color: var(--red); }
.jv-ob-sh-adv-tag { color: var(--text-3); font-style: italic; }
.jv-ob-sh-ok { color: var(--green); font-weight: 500; margin-bottom: 4px; }
.jv-ob-sh-bad { color: var(--red); font-weight: 500; margin-bottom: 4px; }

/* ---- Connect / self-host post-save readiness note (afterSaveRecheckReady). ---- */
.jv-ob-note { font-size: 12.5px; color: var(--text-3); margin-top: 14px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: center; }

@media (max-width: 820px) {
	.jv-ob-body { min-height: 0; padding: 26px 22px 22px; }
	.jv-ob-foot { padding: 14px 22px 20px; }
	.jv-ob-plans { grid-template-columns: 1fr; }
	.jv-ob-form { grid-template-columns: 1fr; }
	.jv-ob-head h1 { font-size: 18px; }
	.jv-ob-foot { flex-wrap: wrap; }
}
@media (prefers-reduced-motion: reduce) {
	.jv-ob-screen { animation: none; }
	.jv-ob-plan, .jv-ob-btn, .jv-ob-inp, .jv-ob-form :deep(.jvc-field) { transition: none; }
	.jv-ob-spinner { animation: none; }
}
</style>
