// Release notice for the mobile PWA, delivered by jarvis_mobile.py boot as
// window.release_notice = {active, version, message}. Mirrors the desktop SPA's
// src/noticeGate.js. Read once at module load — boot values are stable.
import { computed } from "vue";

const n = window.release_notice || {};

export const notice = {
	active: !!n.active,
	version: (n.version || "").trim(),
	message: n.message || "",
};

// Hard gate: blocks the app while a notice is published for this tenant's host,
// until the operator unpublishes it. No per-session dismiss.
export const showNotice = computed(() => notice.active);
