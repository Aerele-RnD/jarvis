// Shared maintenance-hold display logic for both frontends: the SPA imports it as
// `@/maintenanceHold`, the mobile PWA as `@shared/maintenanceHold` (one-way share, see
// pwa/vite.config.js). Keep this a pure ES module - no `@/` imports and no Vue - so
// `node --test` can resolve and run it without a bundler.
//
// The wire payload is minimal: { active, message }. It is a PURE TOGGLE (no TTL, no
// tier) resolved on the control plane tenant -> host -> cell; the bench mirrors it and
// this module only decides whether to show the "back shortly" banner and with what text.

// Show the hold banner iff the resolved notice is active. `active` is the single source
// of truth (the CP already applied the kill-switch + scope resolution).
export function holdShouldShow(notice) {
	return !!(notice && notice.active);
}

// The banner / refusal sentence. `brandName` is a PARAMETER (default "Jarvis"), not an
// import, so this module stays node-testable and single-sourced - the caller passes the
// white-label agent name in, and a customer who renamed the assistant never sees
// "Jarvis" leak. The operator's custom message (already brand-scrubbed server-side)
// wins when present; otherwise the branded default.
export function holdMessage(notice, brandName = "Jarvis") {
	const brand = (brandName || "").trim() || "Jarvis";
	const custom = notice && notice.message ? String(notice.message).trim() : "";
	return custom || `${brand} is upgrading and will be back shortly.`;
}

// Fold a fresh control-plane payload into the current notice, applying the same
// present-vs-unknown discipline the bench uses (Stream E decision 3): a well-formed
// payload (an object that carries `active`) is authoritative and replaces the notice; a
// missing or malformed one is UNKNOWN and keeps the last-known notice, so a partial /
// failed poll can never silently flip a live hold off. Pure, so both the SPA and PWA
// gates share one tested implementation instead of each trusting a raw payload shape.
export function nextNotice(current, fresh) {
	if (!fresh || typeof fresh !== "object" || !("active" in fresh)) return current;
	return { active: !!fresh.active, message: (fresh.message || "").trim() };
}
