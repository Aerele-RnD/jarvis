// Thin wrappers around frappe-ui's `call` (which posts to /api/method/... with
// the session cookie + CSRF). Same backend the Desk chat uses, so conversations
// stay consistent across surfaces.
import { call } from "frappe-ui"

export const listConversations = () => call("jarvis.chat.api.list_conversations")
export const getConversation = (conversation) =>
	call("jarvis.chat.api.get_conversation", { conversation })
export const createOrFocusEmpty = () => call("jarvis.chat.api.create_or_focus_empty")
export const archiveConversation = (conversation) =>
	call("jarvis.chat.api.archive_conversation", { conversation })
export const retryMessage = (message) => call("jarvis.chat.api.retry_message", { message })
export const getChatUiSettings = () => call("jarvis.chat.api.get_chat_ui_settings")
export const isReadyForChat = () => call("jarvis.account.is_ready_for_chat")
export const setConversationModel = (conversation, model) =>
	call("jarvis.chat.api.set_conversation_model", { conversation, model: model || "" })

export async function sendMessage(conversation, message, modelOverride, attachments, context) {
	const args = { conversation, message }
	if (modelOverride) args.model_override = modelOverride
	if (attachments && attachments.length) args.attachments = JSON.stringify(attachments)
	if (context && context.doctype) args.context = JSON.stringify(context)
	return call("jarvis.chat.api.send_message", args)
}

// Mentions: reuse Frappe's built-in Link-field search (no custom backend).
export const searchLink = (doctype, txt) =>
	call("frappe.desk.search.search_link", { doctype, txt: txt || "", page_length: 8 })

// File input: upload to Frappe's File doctype, return {file_url, file_name}.
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
	if (!r.ok) throw new Error(`upload failed (${r.status})`)
	const data = await r.json()
	const f = data.message || data
	return { file_url: f.file_url, file_name: f.file_name || file.name }
}
