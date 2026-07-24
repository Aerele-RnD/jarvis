// Release notice for the mobile PWA, delivered by jarvis_mobile.py boot as
// window.release_notice = {active, title, message, url, latest_version}. Mirrors
// the desktop SPA's src/noticeGate.js. A fleet-wide operator switch — no version
// comparison. Read once at module load — boot values are stable for the page.
import { computed } from "vue";

const n = window.release_notice || {};

export const notice = {
	active: !!n.active,
	title: (n.title || "").trim(),
	message: n.message || "",
	url: (n.url || "").trim(),
	latestVersion: (n.latest_version || "").trim(),
};

// Hard gate: while active it blocks the app until the operator clears it. No
// per-session dismiss.
export const showNotice = computed(() => notice.active && !!notice.title);
