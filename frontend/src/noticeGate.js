// Release notice, delivered by the www/jarvis.py boot payload as
// window.release_notice = {active, version, message}. The control plane decides
// which notice applies to this tenant (per Jarvis Host); this just renders it.
// Read once at module load — boot values are stable for the page's lifetime.
import { computed } from "vue";

const n = window.release_notice || {};

export const notice = {
	active: !!n.active,
	version: (n.version || "").trim(),
	message: n.message || "",
};

// Hard gate: while a notice is published for this tenant's host it stands in
// place of the app, so chat (and every feature) is out of reach until the
// operator unpublishes it. No per-session dismiss.
export const showNotice = computed(() => notice.active);
