// Thin wrappers around frappe-ui's `call` (which posts to /api/method/... with
// the session cookie + CSRF). Same backend the Desk chat uses, so conversations
// stay consistent across surfaces.
import { call } from "frappe-ui"

export const listConversations = () => call("jarvis.chat.api.list_conversations")
export const listTools = () => call("jarvis.chat.api.list_tools")
export const getConversation = (conversation) =>
	call("jarvis.chat.api.get_conversation", { conversation })
// Rich outputs: fetch one canvas/chart artifact's render-ready HTML for an
// assistant message (sandboxed-iframe srcdoc). `name` selects which artifact
// when a message has several.
export const getCanvas = (message, name) =>
	call("jarvis.chat.api.get_canvas", { message, name: name || "" })
// Tabular/text preview for the artifact side panel (xlsx/csv → sheets, txt → text).
export const previewFile = (fileUrl) =>
	call("jarvis.chat.api.preview_file", { file_url: fileUrl })
export const createOrFocusEmpty = () => call("jarvis.chat.api.create_or_focus_empty")
export const archiveConversation = (conversation) =>
	call("jarvis.chat.api.archive_conversation", { conversation })
export const renameConversation = (conversation, title) =>
	call("jarvis.chat.api.rename_conversation", { conversation, title })
export const setStar = (conversation, starred) =>
	call("jarvis.chat.api.set_star", { conversation, starred: starred ? 1 : 0 })
export const retryMessage = (message) => call("jarvis.chat.api.retry_message", { message })
export const getChatUiSettings = () => call("jarvis.chat.api.get_chat_ui_settings")
// Toggle "auto-apply changes" (skip the agent's confirmation step before
// mutating ERP data). Off = confirm every change (default).
export const setAutoApply = (value) =>
	call("jarvis.chat.api.set_auto_apply", { value: value ? 1 : 0 })
// Estimated token usage (this chat / this month / total + monthly budget).
export const getUsage = (conversation) =>
	call("jarvis.chat.api.get_usage", { conversation: conversation || "" })
export const isReadyForChat = () => call("jarvis.account.is_ready_for_chat")

// --- Custom skills (customer-authored, pushed to the container) ---
const SK = "jarvis.chat.custom_skills_api."
export const listCustomSkills = () => call(SK + "list_custom_skills")
export const getCustomSkill = (name) => call(SK + "get_custom_skill", { name })
export const createCustomSkill = (p) => call(SK + "create_custom_skill", p)
export const updateCustomSkill = (p) => call(SK + "update_custom_skill", p)
export const deleteCustomSkill = (name) => call(SK + "delete_custom_skill", { name })
export const applyCustomSkills = () => call(SK + "apply_custom_skills")
export const getCustomSkillsSyncStatus = () => call(SK + "get_custom_skills_sync_status")
export const setConversationModel = (conversation, model) =>
	call("jarvis.chat.api.set_conversation_model", { conversation, model: model || "" })

export async function sendMessage(conversation, message, modelOverride, attachments, context) {
	// Empty conversation is allowed: the backend creates (or focuses) an empty
	// conversation itself and returns its id as `conversation_id` — saves the
	// SPA a createOrFocusEmpty round-trip before the first send (latency plan).
	const args = { conversation: conversation || "", message }
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
