// Customer announcement, delivered by the www/jarvis.py boot payload as
// window.announcement = {active, id, title, message, severity, link_url,
// link_label, interval_days, expires_on}. A SOFT, dismissible banner (unlike the
// release notice's full-page gate) whose re-show cadence lives per-device in
// localStorage via the shared, node-testable `announcementNudge.js`. Mirrors
// src/noticeGate.js's idiom, minus the hard gate / What's-new / recheck.
import { computed, ref } from "vue";
import { bannerShouldShow, writeSnooze, readSnooze } from "@/announcementNudge";
import { session } from "@/data/session";

const a = window.announcement || {};

// Namespace the snooze by the signed-in user (same source noticeGate reads), so
// two people sharing a browser profile keep independent snoozes; guest -> "anon".
const userId = session.user || "anon";

// The boot payload is stable for the page's lifetime, so this is a plain object
// (not reactive): bannerShouldShow()/bannerToneFor() read it, and it never changes.
export const announcement = {
	active: !!a.active,
	id: a.id || "",
	title: a.title || "",
	message: a.message || "",
	severity: a.severity || "",
	link_url: a.link_url || "",
	link_label: a.link_label || "",
	interval_days: Number(a.interval_days) || 7,
};

// The snooze lives in localStorage; this ref mirrors it so the banner hides
// reactively the moment it is dismissed. Seeded from storage at boot (a read-throw
// reads as not-snoozed, so the banner shows - see readSnooze()).
const snooze = ref(readSnooze(userId));

// Reactive: active AND not currently snoozed. `Date.now()` is read at evaluation
// time; the only reactive dependency is `snooze`, so dismissing (which replaces the
// ref below) recomputes this to false and the banner hides.
export const showAnnouncement = computed(
	() => !!announcement.active && bannerShouldShow(announcement, Date.now(), snooze.value)
);

// Dismiss: persist the snooze (best-effort) AND update the ref in-memory so
// `showAnnouncement` flips to false immediately. writeSnooze returns the exact
// record it wrote, so the ref and storage never disagree and the math lives in one
// place (H8) - a localStorage write-throw still hides the banner this session.
export function dismissAnnouncement() {
	snooze.value = writeSnooze(announcement, Date.now(), userId);
}
