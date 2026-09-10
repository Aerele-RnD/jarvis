/**
 * Pre-connect chat status phrases — the copy shown before the first token
 * streams, while the bench is still reaching (or setting up) the assistant.
 *
 * These take priority over tool/thinking phrases in ChatView's `liveStatus`
 * because at this point no tool is running yet: the turn is blocked on the WS
 * connect. Two phases live here:
 *   - "waking"  — a cold/dormant container is spinning back up.
 *   - "pairing" — the one-time device (re)pair (agent 9.3 "Mechanism A"):
 *     the bench has to pair with the gateway before it can talk to it, which
 *     can take tens of seconds. Rendering this (rather than a dead spinner or a
 *     bare "_Stopped._") is the locked UX for the connect-first pairing flow.
 *
 * Kept as a pure function so it can be unit-tested without mounting the
 * 10k-line ChatView SFC. Mirrored by the `liveStatus` computed in ChatView.vue
 * (which calls this first); keep the two in sync.
 */
export function preConnectStatusLabel(phase) {
	if (phase === "waking") return "Waking up your assistant…";
	if (phase === "pairing") return "Setting up your assistant…";
	return null;
}
