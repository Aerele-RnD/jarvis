// Shared announcement-banner display logic for both frontends: the SPA imports it
// as `@/announcementNudge`, the mobile PWA as `@shared/announcementNudge` (one-way
// share, see pwa/vite.config.js). Keep this a pure ES module - no `@/` imports and
// no Vue - so `node --test` can resolve and run it without a bundler.
//
// The wire payload (window.announcement) is: { active, id, title, message,
// severity, link_url, link_label, interval_days, expires_on }. The banner is a
// SOFT, dismissible strip: dismiss snoozes it per-device for `interval_days`, keyed
// by the announcement `id`, so a NEW announcement re-shows even under an old-id
// snooze. Title/body render as PLAIN TEXT (auto-escaped, never v-html) and the CTA
// is scheme-gated (isSafeLink) - the banner's whole XSS-safety rests on both.

export const SNOOZE_KEY = "jarvis-announcement-banner-snooze";

// The SINGLE `until` builder (H8): the caller (writeSnooze AND the gate's dismiss)
// go through this, so the snooze math lives in exactly one place. `interval_days`
// is floored to >= 1 day - a missing / zero / NaN interval defaults to 7, and a
// negative one floors to 1 (never a snooze that has already expired).
export function snoozeUntil(ann, now) {
	const days = Math.max(1, Number(ann.interval_days) || 7);
	return now + days * 86400000;
}

// The banner shows when the announcement is not currently snoozed: no snooze, a
// snooze for a DIFFERENT announcement id (a new announcement supersedes an old
// dismissal), or a snooze that has expired. `now` and `snooze` are passed in so
// this stays pure and testable. (The `active` gate lives in the gate module - this
// is purely the frequency check.)
export function bannerShouldShow(ann, now, snooze) {
	return !snooze || snooze.id !== ann.id || now > snooze.until;
}

// The Banner component's `type`, mapped from the announcement severity. Only
// "Warning" paints amber; everything else (Info, blank, an unknown future value)
// is the neutral "info" blue - never a false-alarm colour.
export function bannerToneFor(ann) {
	const sev = ann && ann.severity ? String(ann.severity).toLowerCase() : "";
	return sev === "warning" ? "warning" : "info";
}

// The CTA is rendered ONLY for an http(s) URL - a scheme gate that blocks
// javascript:/data:/protocol-relative and leading-whitespace tricks (the regex is
// anchored at `^`, so " javascript:" and "\njavascript:" both fail). The banner
// never renders a non-matching link.
export function isSafeLink(url) {
	return /^https?:\/\//i.test(url || "");
}

// Per-user, per-device snooze state. The key is namespaced by `userId` so two
// people sharing a browser profile don't inherit each other's snooze (a missing
// userId falls back to a stable "anon" bucket). `userId` is a PARAMETER, not an
// import, so this module stays node-testable and single-sourced.
//
// Reads/writes are wrapped so a private-mode / quota / absent localStorage never
// throws: a read-throw reads as not-snoozed (banner shows), a write-throw is
// swallowed (the record is still returned so the caller hides the banner this
// session; the snooze just doesn't persist and returns next boot - acceptable).
function snoozeKey(userId) {
	return `${SNOOZE_KEY}:${userId || "anon"}`;
}

export function readSnooze(userId) {
	if (typeof localStorage === "undefined") return null;
	try {
		return JSON.parse(localStorage.getItem(snoozeKey(userId))) || null;
	} catch {
		return null;
	}
}

// Builds the snooze record via the single `until` builder, persists it best-effort,
// and RETURNS it so the caller reuses the exact record (no duplicated math - H8).
export function writeSnooze(ann, now, userId) {
	const record = { id: ann.id, until: snoozeUntil(ann, now) };
	if (typeof localStorage !== "undefined") {
		try {
			localStorage.setItem(snoozeKey(userId), JSON.stringify(record));
		} catch {
			// swallow - a write failure must not break the dismiss; the returned
			// record still hides the banner this session.
		}
	}
	return record;
}
