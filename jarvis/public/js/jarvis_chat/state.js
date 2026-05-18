// Shared mutable state for the page. Kept tiny on purpose — the source of
// truth for messages/conversations is the server; this object only tracks
// what the UI is currently looking at.

export const state = {
	current_conversation: null,
	conversations: [],          // last result of listConversations()
	is_sending: false,          // guard against rapid double-submits
	is_loading_conv: false,     // guard against rapid sidebar clicks
	thinking_timer: null,       // setTimeout id for "Jarvis is thinking…" pill
};
