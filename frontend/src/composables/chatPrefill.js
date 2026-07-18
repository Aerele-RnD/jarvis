import { ref } from "vue"

// Cross-view hand-off for "Discuss in chat" (Skills → Review tab). A review
// row builds a prefilled prompt about a learned pattern, stashes it here and
// router.push("/"); ChatView consumes it ONCE on mount (and clears it on
// EVERY mount so a stale prompt can never fire later): it starts a FRESH
// conversation via newChat(), fills the composer, and when `autoSend` is set
// sends the text as the user's first message in that conversation. Shape:
//   { text: string, autoSend: true }
export const pendingChatPrefill = ref(null)

export function setChatPrefill(payload) {
	pendingChatPrefill.value = payload || null
}

// Read-and-clear: returns the pending payload (or null) and empties the slot
// so a later plain visit to the chat doesn't re-fill a stale prompt.
export function takeChatPrefill() {
	const v = pendingChatPrefill.value
	pendingChatPrefill.value = null
	return v
}
