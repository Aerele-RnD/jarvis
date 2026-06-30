// Thin wrappers around frappe.call so the rest of the app stays decoupled
// from the transport layer.

export async function listConversations() {
	const r = await frappe.call({ method: "jarvis.chat.api.list_conversations" });
	return r.message || [];
}

export async function getConversation(name) {
	const r = await frappe.call({
		method: "jarvis.chat.api.get_conversation",
		args: { conversation: name },
	});
	return r.message;
}

export async function createConversation() {
	const r = await frappe.call({ method: "jarvis.chat.api.create_conversation" });
	return r.message;
}

export async function createOrFocusEmpty() {
	const r = await frappe.call({ method: "jarvis.chat.api.create_or_focus_empty" });
	return r.message;
}

export async function archiveConversation(name) {
	return frappe.call({
		method: "jarvis.chat.api.archive_conversation",
		args: { conversation: name },
	});
}

export async function sendMessage(conversation, message, model_override, attachments, context) {
	const args = { conversation, message };
	if (model_override) args.model_override = model_override;
	if (attachments && attachments.length) {
		args.attachments = JSON.stringify(attachments);
	}
	// `context` = { doctype, name, label } for the doc the user is viewing
	// (floating widget auto-context); the backend prepends it for the agent.
	if (context && context.doctype) {
		args.context = JSON.stringify(context);
	}
	const r = await frappe.call({
		method: "jarvis.chat.api.send_message",
		args,
	});
	return r.message;
}

export async function retryMessage(messageId) {
	const r = await frappe.call({
		method: "jarvis.chat.api.retry_message",
		args: { message: messageId },
	});
	return r.message;
}

export async function getChatUiSettings() {
	const r = await frappe.call({ method: "jarvis.chat.api.get_chat_ui_settings" });
	return r.message || {};
}

export async function setConversationModel(conversation, model) {
	const r = await frappe.call({
		method: "jarvis.chat.api.set_conversation_model",
		args: { conversation, model: model || "" },
	});
	return r.message;
}

export async function setConversationThinking(conversation, thinking) {
	const r = await frappe.call({
		method: "jarvis.chat.api.set_conversation_thinking",
		args: { conversation, thinking: thinking || "" },
	});
	return r.message;
}
