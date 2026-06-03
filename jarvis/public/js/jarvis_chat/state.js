// Shared mutable state for the page. Kept tiny on purpose - the source of
// truth for messages/conversations is the server; this object only tracks
// what the UI is currently looking at.

export const state = {
	current_conversation: null,
	conversations: [],          // last result of listConversations()
	is_sending: false,          // guard against rapid double-submits
	is_loading_conv: false,     // guard against rapid sidebar clicks
	thinking_timer: null,       // setTimeout id for "Jarvis is thinking…" pill

	// Chat-UI LLM settings, populated by api.getChatUiSettings() on init.
	// Used to decide whether to show the per-conversation model picker
	// (oauth mode only) and what its options look like.
	llm_auth_mode: "api_key",
	llm_provider: "",
	llm_model: "",
	subscription_models: {},    // { "OpenAI": [...], "Google Gemini": [...] }

	// Per-conversation model override mirror - refreshed each loadConversation.
	// Empty string means "use llm_model default".
	current_model_override: "",

	// Bundle hash captured at page load. When a re-check on tab refocus
	// returns a different hash, the JS the user is running is older than
	// what the server now ships - banner asks for a refresh.
	build_id: "",
};
