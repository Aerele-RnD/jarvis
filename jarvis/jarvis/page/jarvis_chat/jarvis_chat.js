// The Desk chat page is RETIRED. The canonical chat now lives at the /jarvis
// frappe-ui SPA (apps/jarvis/frontend). This entrypoint just bounces any visit
// to /app/jarvis-chat — including stale bookmarks, workspace links, and the
// mini-chat "expand" — over to /jarvis. The SPA shares the same backend
// (jarvis.chat.api.* + jarvis:event) and conversations, and now carries the
// readiness gate (jarvis.account.is_ready_for_chat → onboarding) itself.
frappe.pages["jarvis-chat"].on_page_load = function () {
	window.location.replace("/jarvis");
};
