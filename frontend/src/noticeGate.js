// Release notice, delivered by the www/jarvis.py boot payload as
// window.release_notice = {active, title, message, url, current_version,
// latest_version, update_available}. update_available is computed server-side
// (installed jarvis vs the operator's latest). The SPA shows a full-page gate
// while this tenant is behind. Read once at module load — boot values are stable
// for the page's lifetime.
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

// Per-session acknowledgement — deliberately NOT persisted, so the notice
// returns on the next fresh load until the tenant updates or the operator clears.
const continued = ref(false);
export function continueSession() {
	continued.value = true;
}

export const showNotice = computed(
	() => notice.active && notice.updateAvailable && !!notice.title && !continued.value
);
