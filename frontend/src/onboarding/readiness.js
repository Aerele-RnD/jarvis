import { isReadyForChat } from "@/api.js"
import { isOnboardComplete } from "@/onboarding/steps.js"

// Shared, memoized readiness verdict. Two callers need it per page load: the
// router's first-navigation guard (bounce an already-onboarded user off a stale
// /onboarding link) and the AppShell onboarding gate (block the app with a
// poster when the workspace was NEVER set up). Sharing one in-flight promise
// keeps it to a SINGLE backend round-trip.
//
// No cache-reset helper is needed: OnboardingView hard-reloads to /jarvis/ on
// completion, which re-mounts the SPA and drops this module-level cache.
let readyPromise = null

// Fail-open: if the backend check THROWS, treat the workspace as ready so a
// flaky/500 check never strands a real user. (Note this only covers thrown
// errors — a returned {ready:false} is a real verdict, handled below.)
export function checkReady() {
	if (!readyPromise) {
		readyPromise = isReadyForChat().catch(() => ({ ready: true }))
	}
	return readyPromise
}

// Resolves true once the workspace is chat-ready. Used by the router guard.
export async function isWorkspaceReady() {
	return isOnboardComplete(await checkReady())
}

// Reasons (from account.py:is_ready_for_chat) that mean "this workspace has
// never completed onboarding" — the FIRST setup step for each mode:
//   - "signup"             managed: no admin api_key yet (wizard not started)
//   - "selfhost_connection" self-host: no validated openclaw connection yet
// Deliberately NOT "llm_credentials": that reason ALSO fires when an
// already-onboarded workspace's LLM creds later expire/rotate. Hard-blocking a
// working workspace out of its chat + data over a recoverable credential
// problem is wrong — that case stays on the existing invite/banner path and
// keeps /account reachable so an admin can reauthorize.
const NOT_ONBOARDED_REASONS = new Set(["signup", "selfhost_connection"])

// True only when the workspace has NOT completed onboarding at all — the single
// case the full-screen gate poster is for. A ready workspace, a fail-open
// (thrown) result, or a merely-degraded one (llm_credentials) all return false.
export async function needsOnboarding() {
	const resp = await checkReady()
	if (isOnboardComplete(resp)) return false
	return NOT_ONBOARDED_REASONS.has(resp && resp.reason)
}
