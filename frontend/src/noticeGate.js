// Release notice, delivered by the www/jarvis.py boot payload as
// window.release_notice = {active, title, message, url, latest_version}. It is a
// fleet-wide operator switch — no version comparison; it shows to every tenant
// while active. Read once at module load — boot values are stable for the page.
import { computed } from "vue";

const n = window.release_notice || {};

export const notice = {
	active: !!n.active,
	title: (n.title || "").trim(),
	message: n.message || "",
	url: (n.url || "").trim(),
	latestVersion: (n.latest_version || "").trim(),
};

// Hard gate: while the operator's notice is active it stands in place of the app,
// so chat (and every feature) is out of reach until the operator clears it. No
// per-session dismiss.
export const showNotice = computed(() => notice.active && !!notice.title);
