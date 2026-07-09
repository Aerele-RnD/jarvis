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
