// Release notice, delivered by the www/jarvis.py boot payload as
// window.release_notice = {active, title, message, url, current_version,
// latest_version, update_available}. update_available is computed server-side
// (installed jarvis vs the operator's latest). Read once at module load — boot
// values are stable for the page's lifetime.
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

// Hard gate: a tenant that is behind the latest version cannot reach chat until
// it updates (or the operator clears the notice). No per-session dismiss — the
// notice stands in place of the app the whole time it applies.
export const showNotice = computed(
	() => notice.active && notice.updateAvailable && !!notice.title
);
