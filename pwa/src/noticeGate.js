// Release notice for the mobile PWA, delivered by jarvis_mobile.py boot as
// window.release_notice = {active, title, message, url, current_version,
// latest_version, update_available}. Mirrors the desktop SPA's src/noticeGate.js.
// Read once at module load — boot values are stable for the page's lifetime.
import { computed } from "vue";

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

// Hard gate: a tenant that is behind the latest version is blocked from chat
// until it updates (or the operator clears the notice). No per-session dismiss.
export const showNotice = computed(
	() => notice.active && notice.updateAvailable && !!notice.title
);
