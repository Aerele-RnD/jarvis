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
						<p class="jv-ob-sub">[mode choice — Tasks 3-5. Placeholder buttons below exercise setMode().]</p>
						<div class="jv-ob-placeholder-actions">
							<button class="jv-ob-btn jv-ob-btn-primary" @click="setMode('managed')">Choose Managed →</button>
							<button class="jv-ob-btn" @click="setMode('selfhost')">Choose Self-hosted →</button>
						</div>
					</div>

					<div v-else-if="state.step === 'account'">
						<p class="jv-ob-placeholder">[managed: account/signup panel — Tasks 3-5]</p>
						<div class="jv-ob-placeholder-actions">
							<button class="jv-ob-btn" @click="goBack">← Back</button>
							<button class="jv-ob-btn jv-ob-btn-primary" @click="goNext">Continue →</button>
						</div>
					</div>

					<div v-else-if="state.step === 'plan'">
						<p class="jv-ob-placeholder">[managed: plan selection panel — Tasks 3-5]</p>
						<div class="jv-ob-placeholder-actions">
							<button class="jv-ob-btn" @click="goBack">← Back</button>
							<button class="jv-ob-btn jv-ob-btn-primary" @click="goNext">Continue →</button>
						</div>
					</div>

					<div v-else-if="state.step === 'pay'">
						<p class="jv-ob-placeholder">[managed: payment panel — Tasks 3-5]</p>
						<div class="jv-ob-placeholder-actions">
							<button class="jv-ob-btn" @click="goBack">← Back</button>
							<button class="jv-ob-btn jv-ob-btn-primary" @click="goNext">Continue →</button>
						</div>
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
import { reactive, computed, onMounted } from "vue"
import { useTheme } from "@/composables/useTheme"
import AppSidebar from "@/components/AppSidebar.vue"
import { STEPS_MANAGED, STEPS_SELFHOST, nextStep, prevStep, stepIndex } from "@/onboarding/steps"
import { checkSignupPaymentState, isReadyForChat } from "@/api"

const { effectiveDark: dark, paletteVars } = useTheme()

// Mirrors jarvis_onboarding.js's STEP_NAMES (~line 212) — the 4 named steps
// shown in managed mode. "mode" and "selfhost" have no header entry.
const STEP_NAMES = ["Account", "Plan", "Pay", "Connect AI"]

// ---- step machine -----------------------------------------------------------
// `state.step` is one of STEPS_MANAGED/STEPS_SELFHOST depending on `state.mode`.
// Kept intentionally small here — Tasks 3-5 add fields as their panels need
// them (email/company/plan choice/etc.), same shape as the desk `state` object.
const state = reactive({ mode: null, step: "mode" })

const steps = computed(() => (state.mode === "selfhost" ? STEPS_SELFHOST : STEPS_MANAGED))

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
// CONCERN (see task-2-report.md): this mapping is inferred, not lifted from
// an equivalent desk code path — revisit once Task 3/4 build the real
// account/pay panels and we know exactly what state they need to resume into.
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
		if (pay && pay.razorpay_order_id) {
			state.mode = "managed"
			state.step = "pay"
		} else if (pay && pay.pending_verification) {
			state.mode = "managed"
			state.step = "account"
		}
		// else: nothing in flight — leave the default "mode" step.
	} catch (e) {
		// Fail-open — never block the wizard from rendering.
	}
}

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

@media (max-width: 520px) {
	.jv-ob-main { padding: 28px 16px 48px; }
	.jv-ob-body { padding: 18px; }
}
</style>
