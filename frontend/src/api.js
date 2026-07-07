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
export const getCanvas = (message, name, dark) =>
	call("jarvis.chat.api.get_canvas", { message, name: name || "", dark: dark ? 1 : 0 })
// Tabular/text preview for the artifact side panel (xlsx/csv → sheets, txt → text).
export const previewFile = (fileUrl) =>
	call("jarvis.chat.api.preview_file", { file_url: fileUrl })
export const createOrFocusEmpty = () => call("jarvis.chat.api.create_or_focus_empty")
export const archiveConversation = (conversation) =>
	call("jarvis.chat.api.archive_conversation", { conversation })
// Danger zone: permanently delete ALL of the user's conversations + messages.
export const clearChatHistory = () => call("jarvis.chat.api.clear_chat_history")
export const renameConversation = (conversation, title) =>
	call("jarvis.chat.api.rename_conversation", { conversation, title })
export const setStar = (conversation, starred) =>
	call("jarvis.chat.api.set_star", { conversation, starred: starred ? 1 : 0 })
export const retryMessage = (message) => call("jarvis.chat.api.retry_message", { message })
export const getChatUiSettings = () => call("jarvis.chat.api.get_chat_ui_settings")
// Toggle per-conversation "auto-apply changes" (skip the write-safety
// confirmation before mutating ERP data). Off = confirm every gated write
// (default). Enabling requires System Manager (a non-admin gets a 403);
// disabling is always allowed for the owner. Response: {ok, data:{auto_apply}}.
export const setAutoApply = (conversation, value) =>
	call("jarvis.chat.api.set_auto_apply", { conversation, value: value ? 1 : 0 })
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
// Run-history dashboard (settings → Macro runs).
export const listMacroRuns = (params) => call(MC + "list_macro_runs", params || {})
export const macroRunStats = () => call(MC + "macro_run_stats")
// Background summarize: fired after every 2+ step save; the WORKER applies the
// summary when the turn ends (macro:merged event) — no client round-trip needed.
// Run is gated on merge_status while pending.
export const summarizeMacro = (name) => call(MC + "summarize_macro", { name })
export const setConversationModel = (conversation, model) =>
	call("jarvis.chat.api.set_conversation_model", { conversation, model: model || "" })

// --- Record draft panel (direct apply, no LLM in the loop) ---
const AC = "jarvis.chat.actions_api."
export const getDoctypeFormMeta = (doctype) => call(AC + "get_doctype_form_meta", { doctype })
export const loadDocForEdit = (doctype, name) => call(AC + "load_doc", { doctype, name })
export const applyAction = (action) => call(AC + "apply_action", { action: JSON.stringify(action) })
// Write-safety gate (issue #186): confirm a parked ERP write by its one-time
// token. Pass the conversation the click came from so the server enforces the
// real conversation guard (#11). Returns the tool result envelope {ok, ...} on
// success, or {ok:False, error:{type:"InvalidConfirmation", ...}} if the token
// is gone.
export const confirmTool = (token, conversation) =>
	call(AC + "confirm_tool", { token, conversation: conversation || "" })
// Resync (issue #186, R3 fix for #3): re-surface the caller's own currently
// parked confirmation cards after a reload/reconnect. Returns
// {ok, data:{pending:[{token, tool, preview, summary, conversation, run_id}]}}.
export const listPendingConfirmations = (conversation) =>
	call(AC + "list_pending_confirmations", { conversation: conversation || "" })

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

// Field metadata for the record-edit action card: powers Link/Select/Date
// controls (returns {ok, doctype, fields:[{fieldname,label,fieldtype,options}]}).
export const getDoctypeFields = (doctype) =>
	call("jarvis.chat.api.get_doctype_fields", { doctype })

// --- LLM pool / models config (System-Manager only, gated server-side) ---
export const getLlmConfig = () => call("jarvis.onboarding.get_llm_config")
export const getPresetCatalog = () => call("jarvis.onboarding.get_preset_catalog")
export const getLlmSyncStatus = () => call("jarvis.onboarding.get_llm_sync_status")
export const saveLlmPool = (models, preset = null, routingMode = "failover") =>
	call("jarvis.onboarding.save_llm_pool", {
		models: JSON.stringify(models),
		preset: preset || "",
		routing_mode: routingMode,
	})

// --- Onboarding wizard (managed signup + self-hosted connect) ---
// Arg names mirror the real backend signatures (jarvis/onboarding.py,
// jarvis/account.py, jarvis/selfhost.py) — verified against the desk wizard's
// frappe.call usage in jarvis/jarvis/page/jarvis_onboarding/jarvis_onboarding.js.
export const listPlans = () => call("jarvis.onboarding.list_plans")
export const getAccountDefaults = () => call("jarvis.onboarding.get_account_defaults")
export const syncConnection = () => call("jarvis.onboarding.sync_connection")
export const startSignup = (email, company, plan) =>
	call("jarvis.onboarding.start_signup", { email, company, plan })
export const checkSignupPaymentState = () => call("jarvis.onboarding.check_signup_payment_state")
export const finishPayment = (payload) => call("jarvis.onboarding.finish_payment", { payload })
export const devOnboard = (email, company, plan) =>
	call("jarvis.onboarding.dev_onboard", { email, company, plan })
export const isOnboarded = () => call("jarvis.account.is_onboarded")
// args: {provider, model, api_key, base_url, auth_mode, force}
export const saveLlmCreds = (args) => call("jarvis.onboarding.save_llm_creds", args)
// args: {base_url, token, deep, stream, tool_user}
export const saveSelfHosted = (args) => call("jarvis.selfhost.save_self_hosted", args)
// args: {base_url, token, deep}
export const testSelfHostConnection = (args) => call("jarvis.selfhost.test_connection", args)

// --- Per-account chat-subscription capture (paste-back OAuth) ---
// begin → { nonce, authorize_url, expires_in }; open authorize_url, sign in,
// paste the redirected URL back → complete captures the account (no side effects).
export const beginPoolAccountSignin = (provider, model) =>
	call("jarvis.oauth.api.begin_pool_account_signin", { provider, model })
// complete is capture-only → { account_ref, label, oauth_blob, account_email }
export const completePoolAccountSignin = (nonce, redirectedUrl) =>
	call("jarvis.oauth.api.complete_pool_account_signin", { nonce, redirected_url: redirectedUrl })

// --- LLM Monitor (System-Manager gated server-side). Real Bifrost usage, NOT the getUsage estimate. ---
export const getLlmUsage = () => call("jarvis.account.get_llm_usage")
export const getLlmConnectionStatus = () => call("jarvis.account.get_llm_connection_status")
export const getAccount = () => call("jarvis.account.get_account")

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

// ── File Box: drop an inbound document, get a directed processing chat ──
export const fileboxDrop = (file_url, file_name) =>
	call("jarvis.chat.filebox.drop_file", { file_url, file_name })
export const fileboxList = () => call("jarvis.chat.filebox.list_inbound", {})

// ── Approvals: pending-decision queue + decide-and-resume ──
export const listApprovals = (status = "Pending") =>
	call("jarvis.chat.approvals_api.list_approvals", { status })
export const approvalsPendingCount = () =>
	call("jarvis.chat.approvals_api.pending_count", {})
export const decideApproval = (name, decision, approve = 1) =>
	call("jarvis.chat.approvals_api.decide", { name, decision, approve })
// Ignore a request off the board (no verdict, no chat resume); reversible.
export const dismissApproval = (name) =>
	call("jarvis.chat.approvals_api.dismiss_approval", { name })
export const restoreApproval = (name) =>
	call("jarvis.chat.approvals_api.restore_approval", { name })

// ── Agents Marketplace: catalog, install/enable/schedule, apply, runs+findings ──
// enable/disable + schedule + config are INSTANT (pure DB writes). Apply is the
// only call that reconciles the container (install/uninstall/update → restart),
// polled via getAgentsSyncStatus exactly like the custom-skills apply pill.
const AG = "jarvis.chat.agents_api."
export const listAgents = () => call(AG + "list_agents")
export const getAgentInstallations = () => call(AG + "get_installations")
export const installAgent = (agent_slug) => call(AG + "install_agent", { agent_slug })
export const uninstallAgent = (installation) => call(AG + "uninstall_agent", { installation })
export const setAgentEnabled = (installation, enabled) =>
	call(AG + "set_enabled", { installation, enabled: enabled ? 1 : 0 })
export const setAgentSchedule = (installation, p) =>
	call(AG + "set_schedule", { installation, ...(p || {}) })
// Engagement / materiality config JSON (benchmark_value, percentage,
// engagement_risk_level, rounding_step → compute_materiality).
export const setAgentConfig = (installation, config) =>
	call(AG + "set_config", { installation, config: JSON.stringify(config || {}) })
export const runAgentNow = (installation) => call(AG + "run_agent_now", { installation })
export const applyAgents = () => call(AG + "apply_agents")
export const getAgentsSyncStatus = () => call(AG + "get_agents_sync_status")
export const listAgentRuns = (agent, limit) =>
	call(AG + "list_runs", { agent: agent || "", limit: limit || 50 })
export const listAgentFindings = (p) => call(AG + "list_findings", p || {})
export const setFindingState = (finding, state) =>
	call(AG + "set_finding_state", { finding, state })
// Role gating + listing admin (System Manager only — the server enforces it;
// the SPA merely probes getAgentAdminOverview and hides the Admin tab on 403).
export const setAgentRoles = (agent_slug, roles) =>
	call(AG + "set_agent_roles", { agent_slug, roles: JSON.stringify(roles || []) })
export const setListingStatus = (agent_slug, status) =>
	call(AG + "set_listing_status", { agent_slug, status })
export const getAgentAdminOverview = () => call(AG + "get_agent_admin_overview")

// ── Paginated feature-page lists (design §2.7) ──────────────────────────────
// One frozen envelope for all four features:
//   { rows, total, has_more, start, page_length[, facets] }  (facets: Approvals only;
//   Approvals first-page responses also carry `awaiting_reply` — chat questions
//   with no approval row behind them, rendered by ApprovalsBoard's strip)
// `_page` normalizes the request args (search/filters/sort/paging) exactly as
// the four backend endpoints expect; `filters` is JSON-encoded here so the SPA
// passes a plain object and the server `frappe.parse_json`s it.
const _page = (p = {}) => ({
	search: p.search || "",
	filters: JSON.stringify(p.filters || {}),
	sort_field: p.sort_field || "",
	sort_dir: p.sort_dir || "",
	start: p.start || 0,
	page_length: p.page_length || 20,
})
export const listCustomSkillsPage = (p) => call(SK + "list_custom_skills_page", _page(p))
export const listMacrosPage = (p) => call(MC + "list_macros_page", _page(p))
export const fileboxListPage = (p) => call("jarvis.chat.filebox.list_inbound_page", _page(p))
export const listApprovalsPage = (p) => call("jarvis.chat.approvals_api.list_approvals_page", _page(p))

// ── File Box FB-1: cascade delete + clear-processed + bulk delete (Q4) ──────
// delete_inbound: owner-gated cascade (approvals + messages + File docs + the
// conversation); refuses while the latest assistant message is streaming.
export const fileboxDelete = (conversation) => call("jarvis.chat.filebox.delete_inbound", { conversation })
// clear_processed_inbound: bulk-delete the caller's done|error rows → {ok, deleted}.
export const fileboxClearProcessed = () => call("jarvis.chat.filebox.clear_processed_inbound")
// delete_inbound_bulk (Q4): same cascade + streaming-refusal per row → {deleted, skipped}.
// List JSON-encoded for parity with the other list-argument wrappers.
export const fileboxDeleteBulk = (conversations) =>
	call("jarvis.chat.filebox.delete_inbound_bulk", { conversations: JSON.stringify(conversations || []) })
