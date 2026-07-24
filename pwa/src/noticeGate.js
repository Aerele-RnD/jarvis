// Release notice for the mobile PWA, delivered by jarvis_mobile.py boot as
// window.release_notice = {active, title, message, url, current_version,
// latest_version, update_available}. Mirrors the desktop SPA's src/noticeGate.js.
// Read once at module load — boot values are stable for the page's lifetime.
import { computed, ref } from "vue";

const n = window.release_notice || {};

export const notice = {
	active: !!n.active,
	title: (n.title || "").trim(),
	message: n.message || "",
	url: (n.url || "").trim(),
	currentVersion: (n.current_version || "").trim(),
	latestVersion: (n.latest_version || "").trim(),
	updateAvailable: !!n.update_available,
};

// Per-session acknowledgement — NOT persisted, so it returns on the next fresh
// load until the tenant updates or the operator clears the notice.
const continued = ref(false);
export function continueSession() {
	continued.value = true;
}

export const showNotice = computed(
	() => notice.active && notice.updateAvailable && !!notice.title && !continued.value
);
