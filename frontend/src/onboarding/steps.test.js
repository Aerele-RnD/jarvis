import { test } from "node:test"
import assert from "node:assert/strict"
import { STEPS_MANAGED, STEPS_SELFHOST, nextStep, prevStep, stepIndex, isOnboardComplete } from "./steps.js"

test("managed step order", () => {
	assert.deepEqual(STEPS_MANAGED, ["mode", "account", "plan", "pay", "connect"])
	assert.equal(nextStep(STEPS_MANAGED, "account"), "plan")
	assert.equal(prevStep(STEPS_MANAGED, "plan"), "account")
	assert.equal(nextStep(STEPS_MANAGED, "connect"), "connect") // clamp at end
	assert.equal(prevStep(STEPS_MANAGED, "mode"), "mode") // clamp at start
})

test("selfhost step order", () => {
	assert.deepEqual(STEPS_SELFHOST, ["mode", "selfhost"])
	assert.equal(nextStep(STEPS_SELFHOST, "mode"), "selfhost")
})

test("stepIndex", () => {
	assert.equal(stepIndex(STEPS_MANAGED, "pay"), 3)
})

// jarvis.account.is_ready_for_chat returns {ready: bool, reason: str|None}
// (see jarvis/account.py::is_ready_for_chat) - isOnboardComplete reads the
// real `ready` field, so this doubles as a real-shape regression test.
test("isOnboardComplete reads readiness", () => {
	assert.equal(isOnboardComplete({ ready: true, reason: null }), true)
	assert.equal(isOnboardComplete({ ready: false, reason: "signup" }), false)
	assert.equal(isOnboardComplete({ ready: false, reason: "llm_credentials" }), false)
	assert.equal(isOnboardComplete(null), false)
	assert.equal(isOnboardComplete(undefined), false)
})
