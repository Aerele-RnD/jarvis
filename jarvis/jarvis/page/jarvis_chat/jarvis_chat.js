// Thin Desk-page entrypoint. The real implementation lives in the
// jarvis_chat bundle so it can be split into modules.
//
// Before loading the chat bundle, gate on jarvis.account.is_ready_for_chat:
// if the customer hasn't completed signup OR hasn't configured their LLM
// credentials for the active auth mode, redirect to /jarvis-onboarding so the
// wizard can collect what's missing. The chat surface assumes both signup
// and LLM credentials are in place, so failing the check would just produce
// confusing errors at first-message time.
//
// Network failures fetching the check are NOT trapped here - we fall through
// to loading the bundle so a transient blip doesn't trap users on the
// onboarding page.

frappe.pages["jarvis-chat"].on_page_load = function (wrapper) {
	frappe.call({ method: "jarvis.account.is_ready_for_chat" })
		.then((r) => {
			if (r && r.message && r.message.ready === false) {
				window.location.assign("/app/jarvis-onboarding");
				return null;
			}
			return frappe.require("jarvis_chat.bundle.js").then(() => {
				if (!window.JarvisChat || typeof window.JarvisChat.init !== "function") {
					frappe.msgprint(__("Jarvis chat bundle failed to load. Run `bench build`."));
					return;
				}
				window.JarvisChat.init(wrapper);
			});
		})
		.catch(() => {
			// Network / server hiccup on the preflight. Fall through to the
			// chat bundle - if the customer really isn't set up the chat code
			// will surface a friendlier error than an opaque redirect.
			return frappe.require("jarvis_chat.bundle.js").then(() => {
				if (!window.JarvisChat || typeof window.JarvisChat.init !== "function") {
					frappe.msgprint(__("Jarvis chat bundle failed to load. Run `bench build`."));
					return;
				}
				window.JarvisChat.init(wrapper);
			});
		});
};
