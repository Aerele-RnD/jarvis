// Drives one connector's sign-in tab end to end: open it, start the flow,
// navigate it to the vendor, then poll until the backend sees a connection.
//
// The tab is opened SYNCHRONOUSLY, before any await - a window.open() issued
// after an awaited call has left the click's user-gesture window and gets
// popup-blocked (same trap LlmPoolEditor's sign-in already works around).
// Its opener is nulled so the vendor's page (which we don't control) can't
// reach back into this tab via window.opener.
//
// connected_at is compared to this call's own started_at, not just checked
// for truthiness: a user re-authorising an already-connected row is
// "connected" on the very first poll, from their PREVIOUS sign-in - only a
// connected_at strictly newer than started_at proves THIS flow finished.
import * as api from "@/api";
import { escapeHtml } from "@/lib/errors";

const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

export async function signIn(name, { label, agentName } = {}) {
	const w = openInterimTab(label, agentName);

	let res;
	try {
		res = await api.connectOauth(name);
	} catch (e) {
		closeTab(w);
		return { status: "error", message: (e && e.message) || "Could not sign in." };
	}
	if (!res || !res.ok || !res.url) {
		closeTab(w);
		return {
			status: "error",
			message: (res && res.error && res.error.message) || "Could not sign in.",
		};
	}

	if (!w) {
		// Popup blocked: fall back to navigating this tab away. The vendor
		// callback page's Back link returns the user with ?settings=connectors
		// so ConnectorsPane can pick the flow back up - nothing left to poll here.
		window.location.href = res.url;
		return { status: "navigated" };
	}
	w.location.href = res.url;
	return pollUntilDone(name, w, res.started_at);
}

// One centered line, no external asset - this tab only exists for the few
// seconds before it navigates to the vendor.
function openInterimTab(label, agentName) {
	let w = null;
	try {
		w = window.open("", "_blank");
	} catch (e) {
		w = null;
	}
	if (!w) return null;
	try {
		w.opener = null;
	} catch (e) {
		/* cross-origin or a browser that disallows the write - harmless either way */
	}
	try {
		w.document.write(
			`<!doctype html><title>${escapeHtml(agentName || "")}</title>` +
				`<body style="margin:0;height:100vh;display:flex;align-items:center;` +
				`justify-content:center;background:#FFFFFF;color:#383838;` +
				`font:14px -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">` +
				`<div>Connecting to ${escapeHtml(label || "")}…</div></body>`
		);
		w.document.close();
	} catch (e) {
		/* interim tab is cosmetic only - a write failure here doesn't block sign-in */
	}
	return w;
}

function closeTab(w) {
	try {
		if (w && !w.closed) w.close();
	} catch (e) {
		/* nothing left to do if a cross-origin tab refuses to close */
	}
}

// Checks the sign-in status once. Returns {done:true, result} once the flow
// has a verdict, or {done:false} to keep polling (including on a network
// error for this tick, which is ignored rather than treated as failure).
async function checkSignInStatus(name, startedAt) {
	let s;
	try {
		s = await api.oauthSigninStatus(name);
	} catch (e) {
		return { done: false };
	}
	if (!s) return { done: false };
	if (s.error) return { done: true, result: { status: "error", message: s.error } };
	if (s.connected && s.connected_at && new Date(s.connected_at) > new Date(startedAt)) {
		return { done: true, result: { status: "connected" } };
	}
	return { done: false };
}

function pollUntilDone(name, w, startedAt) {
	const deadline = Date.now() + POLL_TIMEOUT_MS;
	return new Promise((resolve) => {
		async function tick() {
			const outcome = await checkSignInStatus(name, startedAt);
			if (outcome.done) {
				closeTab(w);
				resolve(outcome.result);
				return;
			}
			if (w && w.closed) {
				// The callback may have landed a moment before the user closed the
				// tab - give it one more chance before calling the sign-in abandoned.
				const second = await checkSignInStatus(name, startedAt);
				resolve(second.done ? second.result : { status: "closed" });
				return;
			}
			if (Date.now() >= deadline) {
				// Leave the tab open - the user may still be mid-flow in it.
				resolve({ status: "timeout" });
				return;
			}
			setTimeout(tick, POLL_INTERVAL_MS);
		}
		setTimeout(tick, POLL_INTERVAL_MS);
	});
}
