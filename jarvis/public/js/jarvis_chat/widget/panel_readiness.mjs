// Chat-readiness classification for the floating widget panel.
//
// DUPLICATED from frontend/src/onboarding/readiness.js by necessity, not by
// choice: this widget is plain Vue + .mjs served straight into Desk (see
// jarvis_widget.bundle.js) and cannot import from frontend/src or use the "@/"
// alias the SPA's Vite build resolves. Keep NOT_ONBOARDED_REASONS and the
// fail-open contract below in sync with that file BY HAND. See its comments
// for the full reasoning behind each reason's placement - repeated here only
// to the extent this module needs it to classify a verdict.

// Reasons meaning the workspace has NEVER completed onboarding at all - the
// only case that should replace the whole panel with a setup nudge.
// Deliberately excludes "llm_credentials": that reason ALSO fires when an
// already-working workspace's LLM creds later expire or rotate, and hard
// gating such a workspace out of its own chat is wrong. It falls through to
// "degraded" instead, which keeps the chat usable and only warns.
const NOT_ONBOARDED_REASONS = new Set([
  "signup",
  "selfhost_connection",
  "llm_pool_provisioning",
  "llm_provisioning",
]);

// Three-way verdict the panel renders around:
//  - "ready"    chat works, render the panel as normal.
//  - "gate"     never onboarded, replace the body with the setup nudge.
//  - "degraded" onboarded once but not currently chat-ready (e.g. expired
//               creds, a paused subscription); keep the composer, add a
//               banner explaining a send may fail.
//
// `resp` is whatever jarvis.account.is_ready_for_chat returned. Fail OPEN to
// "ready" on a missing/falsy response - a thrown or timed-out check must
// never strand a real user behind a scary gate (mirrors readiness.js's own
// checkReady(), which catches the backend call into {ready: true}).
export function classifyReadiness(resp) {
  if (!resp || resp.ready) return "ready";
  return NOT_ONBOARDED_REASONS.has(resp.reason) ? "gate" : "degraded";
}

// Copy for the degraded banner. Prefers the backend's OWN explanation
// (`detail`, e.g. admin's chat_readiness_reason for a stalled container or a
// suspended subscription) over invented text - same precedent as
// readiness.js's readinessDetailOf(). Most degraded reasons (llm_credentials
// in particular) carry no `detail`, so those fall back to a generic sentence
// rather than one guessed per reason code, which would drift from account.py.
export function degradedMessage(resp) {
  const detail = (resp && resp.detail) || "";
  if (detail) return detail;
  return "Jarvis isn't fully set up, so replies may fail. Ask your administrator to finish reconnecting it.";
}
