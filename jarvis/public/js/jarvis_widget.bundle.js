// Global floating Jarvis widget — a draggable, edge-snapping shortcut FAB
// that navigates to the Jarvis chat SPA (a fresh conversation), present on
// every Desk page EXCEPT the full chat page (and the onboarding flow, where
// the agent isn't ready yet).
//
// Mounted ONCE into a <body>-level host so it survives SPA navigation: its
// dragged position persists (via localStorage) as you move between
// invoices/reports. Route changes only toggle the host's visibility.

import { createApp } from "vue";
import Widget from "./jarvis_chat/widget/Widget.vue";

(function () {
	if (window.__jarvisWidgetBooted) return;

	// Routes where the floating widget should NOT appear.
	const HIDE_ON = ["jarvis-chat", "jarvis-onboarding"];

	let host = null;

	function ensureMounted() {
		if (host) return;
		host = document.createElement("div");
		host.id = "jarvis-widget-host";
		document.body.appendChild(host);
		createApp(Widget).mount(host);
	}

	function sync() {
		ensureMounted();
		const route = (window.frappe && frappe.get_route && frappe.get_route()) || [];
		const hide = HIDE_ON.indexOf(route[0] || "") !== -1;
		host.style.display = hide ? "none" : "";
	}

	function start() {
		if (!window.frappe) return;
		window.__jarvisWidgetBooted = true;
		sync();
		if (frappe.router && frappe.router.on) frappe.router.on("change", sync);
	}

	// Desk may not be fully booted when this include runs.
	if (window.frappe && window.frappe.router) {
		start();
	} else if (window.$) {
		$(start);
	} else {
		document.addEventListener("DOMContentLoaded", start);
	}
})();
