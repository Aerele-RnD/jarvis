// Thin wrappers around frappe-ui's `call` (which posts to /api/method/... with
// the session cookie + CSRF). Same backend the Desk chat uses, so conversations
// stay consistent across surfaces.
import { call } from "frappe-ui"

export const listConversations = () => call("jarvis.chat.api.list_conversations")
export const getConversation = (conversation) =>
	call("jarvis.chat.api.get_conversation", { conversation })
// Rich outputs: fetch one canvas/chart artifact's render-ready HTML for an
// assistant message (sandboxed-iframe srcdoc). `name` selects which artifact
// when a message has several.
export const getCanvas = (message, name, dark) =>
	call("jarvis.chat.api.get_canvas", { message, name: name || "", dark: dark ? 1 : 0 })
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
// Skill sharing: owner shares a skill with specific users (read-only for them).
export const listShareableUsers = () => call(SK + "list_shareable_users")
export const getSkillShares = (name) => call(SK + "get_skill_shares", { name })
export const shareCustomSkill = (name, users) => call(SK + "share_custom_skill", { name, users: JSON.stringify(users || []) })

// --- Macros (customer-authored prompt sequences run as chained turns) ---
const MC = "jarvis.chat.macros_api."
export const listMacros = () => call(MC + "list_macros")
export const getMacro = (name) => call(MC + "get_macro", { name })
export const createMacro = (p) => call(MC + "create_macro", { ...p, steps: JSON.stringify(p.steps || []) })
export const updateMacro = (p) => {
	const args = { ...p }
	if (p.steps !== undefined) args.steps = JSON.stringify(p.steps)
	return call(MC + "update_macro", args)
}
export const deleteMacro = (name) => call(MC + "delete_macro", { name })
export const runMacro = (name) => call(MC + "run_macro", { name })
export const stopMacroRun = (run) => call(MC + "stop_macro_run", { run })
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

// Field metadata for the record-edit action card: powers Link/Select/Date
// controls (returns {ok, doctype, fields:[{fieldname,label,fieldtype,options}]}).
export const getDoctypeFields = (doctype) =>
	call("jarvis.chat.api.get_doctype_fields", { doctype })

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
