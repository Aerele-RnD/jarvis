// Pure step-progression helpers for the onboarding wizard. No Vue, no API
// calls - kept pure so they're cheap to unit-test with node --test (see
// steps.test.js) and reusable from both the wizard component and the
// router's first-run guard.

// Managed flow (2026-07 redesign): intro tour → Plan → Details → Pay → Connect.
// The old "mode" chooser + "account" step are gone; self-host is reached via a
// quiet link on the Plan step and keeps its single "selfhost" step.
export const STEPS_MANAGED = ["intro", "plan", "details", "pay", "connect"]
export const STEPS_SELFHOST = ["plan", "selfhost"]

export function stepIndex(steps, cur) {
	const i = steps.indexOf(cur)
	return i < 0 ? 0 : i
}

export function nextStep(steps, cur) {
	return steps[Math.min(stepIndex(steps, cur) + 1, steps.length - 1)]
}

export function prevStep(steps, cur) {
	return steps[Math.max(stepIndex(steps, cur) - 1, 0)]
}

// jarvis.account.is_ready_for_chat (jarvis/account.py) returns
// {ready: bool, reason: str|None} - reason is one of "signup" /
// "llm_credentials" / "selfhost_connection" when not ready, null when ready.
// Onboarding is "complete" (chat-ready) exactly when `ready` is true.
export function isOnboardComplete(readyResp) {
	return !!(readyResp && readyResp.ready)
}

// Branch decision for the "I've verified my email" poll. Admin's
// get_signup_payment_state (jarvis_admin_v2/billing/signup.py) returns one of
// THREE shapes: still-pending, paid-plan order handles, or the free/trial
// completion {pending_verification: false, subscription_status: "..."} with
// no order (verification WAS the whole signup). Pure so the free-plan branch
// - the one that used to dead-end on "Signup state has changed" - stays
// unit-tested.
//   {kind: "wait"}                  - link not clicked yet (or empty resp)
//   {kind: "checkout"}              - paid plan: open Razorpay Checkout
//   {kind: "complete"}              - free/trial plan: already Active, skip
//                                     payment and go straight to provisioning
//   {kind: "halted", status: "..."} - Cancelled/Expired/etc: dead sub, tell
//                                     the customer instead of the generic
//                                     "state changed" shrug
//   {kind: "stale"}                 - unrecognized shape: ask for a refresh
export function verifyPollAction(d) {
	if (!d || d.pending_verification) return { kind: "wait" }
	if (d.razorpay_order_id) return { kind: "checkout" }
	if (d.subscription_status === "Active") return { kind: "complete" }
	if (d.subscription_status) return { kind: "halted", status: String(d.subscription_status) }
	return { kind: "stale" }
}
