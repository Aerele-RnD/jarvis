frappe.pages["jarvis-onboarding"].on_page_load = function (wrapper) {
	// Onboarding now lives in the Jarvis SPA. Thin redirect only (Phase 3 cleanup).
	frappe.ui.make_app_page({ parent: wrapper, title: "Connect to Jarvis", single_column: true });
	window.location.replace("/jarvis/onboarding");
};
