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

export async function sendMessage(conversation, message) {
	const r = await frappe.call({
		method: "jarvis.chat.api.send_message",
		args: { conversation, message },
	});
	return r.message;
}
