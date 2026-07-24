import { test } from "node:test";
import assert from "node:assert/strict";
import {
	STEPS_MANAGED,
	STEPS_SELFHOST,
	nextStep,
	prevStep,
	stepIndex,
	isOnboardComplete,
	verifyPollAction,
	suspensionNotice,
	SUSPENDED_FALLBACK,
} from "./steps.js";

test("managed step order", () => {
	assert.deepEqual(STEPS_MANAGED, ["intro", "plan", "details", "pay", "connect"]);
	assert.equal(nextStep(STEPS_MANAGED, "plan"), "details");
	assert.equal(prevStep(STEPS_MANAGED, "details"), "plan");
	assert.equal(nextStep(STEPS_MANAGED, "connect"), "connect"); // clamp at end
	assert.equal(prevStep(STEPS_MANAGED, "intro"), "intro"); // clamp at start
});

test("selfhost step order", () => {
	assert.deepEqual(STEPS_SELFHOST, ["plan", "selfhost"]);
	assert.equal(nextStep(STEPS_SELFHOST, "plan"), "selfhost");
	assert.equal(prevStep(STEPS_SELFHOST, "selfhost"), "plan");
});

test("stepIndex", () => {
	assert.equal(stepIndex(STEPS_MANAGED, "pay"), 3);
});

// jarvis.account.is_ready_for_chat returns {ready: bool, reason: str|None}
// (see jarvis/account.py::is_ready_for_chat) - isOnboardComplete reads the
// real `ready` field, so this doubles as a real-shape regression test.
test("isOnboardComplete reads readiness", () => {
	assert.equal(isOnboardComplete({ ready: true, reason: null }), true);
	assert.equal(isOnboardComplete({ ready: false, reason: "signup" }), false);
	assert.equal(isOnboardComplete({ ready: false, reason: "llm_credentials" }), false);
	assert.equal(isOnboardComplete(null), false);
	assert.equal(isOnboardComplete(undefined), false);
});

// verifyPollAction consumes admin's get_signup_payment_state shapes verbatim
// (jarvis_admin_v2/billing/signup.py::get_signup_payment_state docstring).
// The "complete" case is the free-plan fix: {pending_verification: false,
// subscription_status: "Active"} with NO razorpay_order_id used to fall
// through every branch and dead-end the wizard.
test("verifyPollAction: link not clicked yet keeps waiting", () => {
	assert.deepEqual(verifyPollAction({ pending_verification: true }), { kind: "wait" });
	assert.deepEqual(verifyPollAction(null), { kind: "wait" });
	assert.deepEqual(verifyPollAction(undefined), { kind: "wait" });
});

test("verifyPollAction: paid plan goes to checkout", () => {
	const d = {
		pending_verification: false,
		razorpay_order_id: "order_x",
		razorpay_key_id: "rzp_test",
		amount_inr: 2000,
		customer_password: "pw",
	};
	assert.deepEqual(verifyPollAction(d), { kind: "checkout", provider: "razorpay" });
});

test("verifyPollAction: autopay-trial (subscription) plan goes to checkout", () => {
	// Admin's poll shape for a paid plan with trial_days: a Razorpay
	// SUBSCRIPTION id (mandate-auth Checkout), no order id.
	const d = {
		pending_verification: false,
		razorpay_subscription_id: "sub_x",
		razorpay_key_id: "rzp_test",
		amount_inr: 999,
		trial_days: 14,
		customer_password: "pw",
	};
	assert.deepEqual(verifyPollAction(d), { kind: "checkout", provider: "razorpay" });
});

test("verifyPollAction: cashfree paid plan goes to checkout (provider labeled)", () => {
	// Admin's poll shape for a Cashfree paid plan: a payment_session_id (the
	// token the Cashfree SDK checks out against) + the provider discriminator.
	const d = {
		pending_verification: false,
		payment_provider: "cashfree",
		cashfree_order_id: "cforder_x",
		payment_session_id: "session_x",
		cashfree_app_id: "app_x",
		cashfree_env: "sandbox",
		amount_inr: 2000,
	};
	assert.deepEqual(verifyPollAction(d), { kind: "checkout", provider: "cashfree" });
});

// Autopay monthly on Cashfree resumes with a MANDATE token, not an order one.
// Before this was recognised the customer landed on "stale" and could not pay.
test("verifyPollAction: cashfree autopay mandate goes to checkout", () => {
	const d = {
		pending_verification: false,
		payment_provider: "cashfree",
		cashfree_subscription_id: "jrvs_x",
		subscription_session_id: "sub_session_x",
		cashfree_app_id: "app_x",
		cashfree_env: "sandbox",
	};
	assert.deepEqual(verifyPollAction(d), { kind: "checkout", provider: "cashfree" });
});

test("verifyPollAction: cashfree mandate inferred from subscription_session_id alone", () => {
	const d = { pending_verification: false, subscription_session_id: "sub_session_x" };
	assert.deepEqual(verifyPollAction(d), { kind: "checkout", provider: "cashfree" });
});

test("verifyPollAction: cashfree inferred from payment_session_id when provider absent", () => {
	const d = { pending_verification: false, payment_session_id: "session_y", amount_inr: 500 };
	assert.deepEqual(verifyPollAction(d), { kind: "checkout", provider: "cashfree" });
});

test("verifyPollAction: free plan already Active completes without payment", () => {
	const d = {
		pending_verification: false,
		subscription_status: "Active",
		customer_password: "pw",
	};
	assert.deepEqual(verifyPollAction(d), { kind: "complete" });
});

test("verifyPollAction: terminal statuses surface as halted", () => {
	for (const status of ["Cancelled", "Expired", "Past Due"]) {
		assert.deepEqual(
			verifyPollAction({ pending_verification: false, subscription_status: status }),
			{ kind: "halted", status },
		);
	}
});

test("verifyPollAction: unknown shape asks for a refresh", () => {
	assert.deepEqual(verifyPollAction({ pending_verification: false }), { kind: "stale" });
	assert.deepEqual(verifyPollAction({}), { kind: "stale" });
});

test("suspensionNotice: only fires for a suspended workspace", () => {
	// Entitled / ready / absent → no banner.
	assert.equal(suspensionNotice({ ready: true }), null);
	assert.equal(suspensionNotice(null), null);
	assert.equal(suspensionNotice(undefined), null);
	// A different not-ready reason must NOT raise the billing banner — that
	// would tell a customer mid-provisioning to go pay again.
	assert.equal(suspensionNotice({ ready: false, reason: "container_provisioning" }), null);
	assert.equal(suspensionNotice({ ready: false, reason: "llm_credentials" }), null);
});

test("suspensionNotice: prefers admin's sentence, falls back when absent", () => {
	assert.equal(
		suspensionNotice({
			ready: false,
			reason: "subscription_suspended",
			detail: "Your subscription has expired. Renew to restore access to Jarvis.",
		}),
		"Your subscription has expired. Renew to restore access to Jarvis.",
	);
	// Older admin sends the state with no reason string.
	assert.equal(
		suspensionNotice({ ready: false, reason: "subscription_suspended" }),
		SUSPENDED_FALLBACK,
	);
	assert.equal(
		suspensionNotice({ ready: false, reason: "subscription_suspended", detail: "" }),
		SUSPENDED_FALLBACK,
	);
});
