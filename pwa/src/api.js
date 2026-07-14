// Thin wrappers around frappe-ui's `call` (POSTs /api/method/... with the
// session cookie + CSRF header). The PWA is served BY the site, so it is the
// same auth the Desk and the desktop SPA use — no pairing token, no QR: that
// flow only exists in the native app because it lives on another origin.
//
// Deliberately its own module rather than an import of the SPA's api.js: this
// surface needs ~10 of that file's 60-odd endpoints, and keeping it separate
// means the phone bundle can't be grown by a change made for the desktop.
import { call } from "frappe-ui"

const CHAT = "jarvis.chat.api."

export const listConversations = () => call(CHAT + "list_conversations")
export const getConversation = (conversation) => call(CHAT + "get_conversation", { conversation })
export const archiveConversation = (conversation) =>
	call(CHAT + "archive_conversation", { conversation })
export const renameConversation = (conversation, title) =>
	call(CHAT + "rename_conversation", { conversation, title })

// An empty `conversation` is allowed: the backend creates (or focuses) the
// user's empty conversation and returns its id as `conversation_id`, which
// saves the new-chat round-trip before the very first send.
export const sendMessage = (conversation, message) =>
	call(CHAT + "send_message", { conversation: conversation || "", message })

export const stopRun = (conversation, runId) =>
	call(CHAT + "stop_run", { conversation, run_id: runId || "" })

export const listCustomSkills = () => call("jarvis.chat.custom_skills_api.list_custom_skills")
