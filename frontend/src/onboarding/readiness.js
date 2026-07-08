import { isReadyForChat } from "@/api.js"
import { isOnboardComplete } from "@/onboarding/steps.js"

// Shared, memoized "is this workspace onboarded?" verdict.
//
// Two callers need it on every page load: the router's first-navigation guard
// (bounce an already-onboarded user off a stale /onboarding link) and the
// AppShell onboarding gate (block the app with a poster until setup is done).
// Sharing one in-flight promise keeps it to a SINGLE backend round-trip and —
// because both read the same resolved value — makes the gate and the router
// flip together, so the poster never flashes chat before it appears.
//
// No cache-reset helper is needed: OnboardingView hard-reloads to /jarvis/ on
// completion (window.location.assign), which re-mounts the SPA and drops this
// module-level cache naturally, so the next check reads the now-ready state.
let readyPromise = null

// Fail-open: if the backend check throws, treat the workspace as ready so a
// flaky/500 check never strands a real user behind the gate unable to chat.
export function checkReady() {
	if (!readyPromise) {
		readyPromise = isReadyForChat().catch(() => ({ ready: true }))
	}
	return readyPromise
}

// Resolves true once the workspace has completed onboarding (chat-ready).
export async function isWorkspaceReady() {
	return isOnboardComplete(await checkReady())
}
