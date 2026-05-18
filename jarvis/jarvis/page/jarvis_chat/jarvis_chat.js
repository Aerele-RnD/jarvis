// Thin Desk-page entrypoint. The real implementation lives in the
// jarvis_chat bundle so it can be split into modules.

frappe.pages["jarvis-chat"].on_page_load = function (wrapper) {
	frappe.require("jarvis_chat.bundle.js").then(() => {
		if (!window.JarvisChat || typeof window.JarvisChat.init !== "function") {
			frappe.msgprint(__("Jarvis chat bundle failed to load. Run `bench build`."));
			return;
		}
		window.JarvisChat.init(wrapper);
	});
};
