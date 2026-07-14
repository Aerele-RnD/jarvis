// Thin wrappers around frappe-ui's `call` (POSTs /api/method/... with the
// session cookie + CSRF header). The PWA is served BY the site, so it is the
// same auth the Desk and the desktop SPA use — no pairing token, no QR: that
// flow only exists in the native app because it lives on another origin.
//
// Deliberately its own module rather than an import of the SPA's api.js: this
// surface needs ~20 of that file's 60-odd endpoints, and keeping it separate
// means the phone bundle can't be grown by a change made for the desktop.
// Voice is the exception — see transcribeAudio below.
import { call } from "frappe-ui"

const CHAT = "jarvis.chat.api."

export const listConversations = () => call(CHAT + "list_conversations")
export const getConversation = (conversation) => call(CHAT + "get_conversation", { conversation })
export const archiveConversation = (conversation) =>
	call(CHAT + "archive_conversation", { conversation })
export const renameConversation = (conversation, title) =>
	call(CHAT + "rename_conversation", { conversation, title })
export const setStar = (conversation, starred) =>
	call(CHAT + "set_star", { conversation, starred: starred ? 1 : 0 })
export const setAutoApply = (conversation, value) =>
	call(CHAT + "set_auto_apply", { conversation, value: value ? 1 : 0 })

// Model name for the chat header + whether the mic is allowed to appear (STT is
// off unless the admin configured a transcription key).
export const getChatUiSettings = () => call(CHAT + "get_chat_ui_settings")

// An empty `conversation` is allowed: the backend creates (or focuses) the
// user's empty conversation and returns its id as `conversation_id`, which
// saves the new-chat round-trip before the very first send.
export const sendMessage = (conversation, message, attachments = []) =>
	call(CHAT + "send_message", {
		conversation: conversation || "",
		message,
		...(attachments.length ? { attachments: JSON.stringify(attachments) } : {}),
	})

export const stopRun = (conversation, runId) =>
	call(CHAT + "stop_run", { conversation, run_id: runId || "" })

// A message's rich outputs (charts, generated images, files). `get_conversation`
// returns the item list on `message.canvas`; this fetches one item's body.
export const getCanvas = (message, name = "", dark = 0) =>
	call(CHAT + "get_canvas", { message, name, dark })

// Render-ready preview of a tabular/text artifact (xlsx/csv → sheets, txt → text).
export const previewFile = (file_url) => call(CHAT + "preview_file", { file_url })

export const listCustomSkills = () => call("jarvis.chat.custom_skills_api.list_custom_skills")

// ── Write approvals (the write-safety gate) ─────────────────────────────────
// A tool that would change ERP data is parked server-side and announced as an
// `action:pending` event carrying a one-time token. confirm_tool is the ONLY
// path that runs the parked call. There is no deny endpoint by design: dropping
// the card leaves the token to expire, which is exactly what "no" means.
export const listPendingConfirmations = (conversation) =>
	call("jarvis.chat.actions_api.list_pending_confirmations", { conversation: conversation || "" })
export const confirmTool = (token, conversation) =>
	call("jarvis.chat.actions_api.confirm_tool", { token, conversation: conversation || "" })

// ── Approval queue (Jarvis Approval: the agent asking a human a question) ───
export const listApprovals = (status = "Pending", limit = 50) =>
	call("jarvis.chat.approvals_api.list_approvals", { status, limit })
export const pendingApprovalsCount = () => call("jarvis.chat.approvals_api.pending_count")
export const decideApproval = (name, decision, approve) =>
	call("jarvis.chat.approvals_api.decide", { name, decision, approve: approve ? 1 : 0 })

// ── Attachments ────────────────────────────────────────────────────────────
// Standard Frappe upload, private by default: a chat attachment is the user's
// document, not a public asset. Same shape the SPA's uploadFile uses.
export async function uploadFile(file) {
	const fd = new FormData()
	fd.append("file", file, file.name)
	fd.append("is_private", "1")
	const r = await fetch("/api/method/upload_file", {
		method: "POST",
		headers: { "X-Frappe-CSRF-Token": window.csrf_token || "" },
		body: fd,
		credentials: "include",
	})
	if (!r.ok) throw new Error(`Couldn't upload ${file.name} (${r.status})`)
	const data = await r.json()
	const f = data.message || data
	return { file_url: f.file_url, file_name: f.file_name || file.name }
}

// Dictation goes through the SPA's module unchanged: same endpoint, same 25s
// client cap, same error unwrapping. The mic is a place where two subtly
// different clients would be two subtly different bugs.
export { transcribeAudio } from "@shared/api/voice.js"
