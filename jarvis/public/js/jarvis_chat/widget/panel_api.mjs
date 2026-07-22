// Thin wrappers over the Desk's own frappe.call. The panel runs INSIDE the
// Desk, so the session cookie and CSRF token are already in place — unlike the
// SPA and the PWA, this surface needs no frappe-ui and no socket of its own.
//
// frappe.call resolves to the full envelope; every caller here wants
// `.message`, so unwrap it once at this boundary.

const CHAT = "jarvis.chat.api.";
const ACTIONS = "jarvis.chat.actions_api.";

function call(method, args) {
  return frappe.call({ method, args: args || {} }).then((r) => r.message);
}

export const listConversations = () => call(CHAT + "list_conversations");

export const getConversation = (conversation) => call(CHAT + "get_conversation", { conversation });

// An empty `conversation` is allowed: the backend creates (or focuses) the
// user's empty conversation and returns its id as `conversation_id`, which
// saves a round-trip before the very first send.
//
// `context` is the object from desk_context.contextFromRoute. Send it only when
// there is one, so a non-record page behaves as a plain chat.
export const sendMessage = (conversation, message, context) =>
  call(CHAT + "send_message", {
    conversation: conversation || "",
    message,
    ...(context ? { context: JSON.stringify(context) } : {}),
  });

export const stopRun = (conversation, runId) =>
  call(CHAT + "stop_run", { conversation, run_id: runId || "" });

// Resolves a write-confirmation gate raised by an `action:pending` frame.
export const confirmTool = (token, conversation) =>
  call(ACTIONS + "confirm_tool", { token, conversation: conversation || "" });
