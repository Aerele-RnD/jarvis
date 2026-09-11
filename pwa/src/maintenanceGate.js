// Maintenance hold for the mobile PWA, delivered by jarvis_mobile.py boot as
// window.maintenance = { active, message }. Mirrors the desktop SPA's
// frontend/src/maintenanceGate.js in the PWA's idiom, and is the sibling of this
// dir's noticeGate.js. One deliberate difference from noticeGate: this state is
// REACTIVE, not a page-lifetime constant - an upgrade hold is raised and cleared
// WHILE the customer is mid-chat, so the strip, the avatar's "upgrading" mood and
// the send refusal must all flip live. Pure toggle (no TTL/tier), already resolved
// + kill-switched on the control plane.
import { computed, ref } from "vue";
import { call } from "frappe-ui";
import { holdShouldShow, holdMessage, nextNotice } from "@shared/maintenanceHold";
import { agentName } from "@/branding";

const boot = window.maintenance || {};
const notice = ref({ active: !!boot.active, message: (boot.message || "").trim() });

// True while the upgrade hold is up. Drives the top-of-app strip, the empty-state
// avatar's "upgrading" mood, and the send refusal.
export const holdActive = computed(() => holdShouldShow(notice.value));

// The strip / refusal sentence, white-label aware (agentName from branding; the
// operator's brand-scrubbed custom message wins when set).
export const holdText = computed(() => holdMessage(notice.value, agentName));

export const rechecking = ref(false);

// Raise the hold locally from a server refusal: if the tab was already open when the
// operator set the hold, boot never carried it; the first blocked send comes back with
// reason "maintenance", and ChatView calls this so the strip + mood show without a
// reload. The server refusal carries only a reason today (no message), so `message` is
// normally empty and the boot-seeded / branded-default copy is kept.
export function raiseHold(message) {
	const msg = (message || "").trim();
	notice.value = { active: true, message: msg || notice.value.message };
	_startPoll();
}

// Clear the hold locally. Called when a send is ACCEPTED - proof the CP-side gate passed
// (the roll finished) - so the strip + avatar lift immediately instead of on reload or
// the next poll. Idempotent.
export function clearHold() {
	if (notice.value.active) notice.value = { active: false, message: "" };
	_stopPoll();
}

// Re-pull the hold from the control plane so an open tab lifts it promptly when the roll
// clears. Keeps the last-known notice on any error or malformed shape (via nextNotice) -
// a failed poll must never flip a live hold off.
export async function recheck() {
	if (rechecking.value) return holdActive.value;
	rechecking.value = true;
	try {
		const fresh = await call("jarvis.maintenance_notice.check");
		notice.value = nextNotice(notice.value, fresh);
	} catch (e) {
		/* keep last-known: a failed poll must not clear a live hold */
	} finally {
		rechecking.value = false;
	}
	// Keep the poll in lockstep with the actual state: a recheck usually CLEARS the
	// hold (stop polling), but folding in a genuinely-new CP hold could re-raise it, so
	// (re)start rather than only ever stopping.
	if (holdActive.value) _startPoll();
	else _stopPoll();
	return holdActive.value;
}

// While a hold is up, re-check the CP on a slow cadence so an IDLE tab (one that never
// sends again after the roll finishes) still lifts the strip. The send path clears it
// instantly for an active user (clearHold); this covers the rest. Runs only while held:
// started on raise / boot, stopped on clear.
const POLL_MS = 60000;
let _pollTimer = null;
function _startPoll() {
	if (_pollTimer || typeof setInterval !== "function") return;
	_pollTimer = setInterval(() => {
		recheck();
	}, POLL_MS);
}
function _stopPoll() {
	if (_pollTimer) {
		clearInterval(_pollTimer);
		_pollTimer = null;
	}
}
if (notice.value.active) _startPoll();
