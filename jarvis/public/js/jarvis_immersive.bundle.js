// Global immersive chrome for the customer-facing Jarvis Desk pages.
//
// Loaded on EVERY Desk page via hooks.app_include_js. On the Jarvis routes
// (chat / onboarding / account) it hides the Frappe navbar + page-head so the
// page reads as a native full-screen product; it reverts on every other route.
//
// Why a global content-hashed bundle (not the page CSS): a hashed asset can't
// be served stale the way a plain CSS file can — that was why the header
// "wouldn't disappear" on the account page. It also covers onboarding +
// account, which have no chat bundle of their own.
//
// The account + onboarding pages already paint a full-viewport `position:fixed`
// overlay (.ja-bg / .jo-bg, inset:0), so once the navbar is hidden they use the
// whole screen on their own — no extra layout CSS needed. The chat page manages
// its own height (mount.js); dropping the navbar's vertical space is enough.

(function () {
	if (window.__jarvisImmersive) return;
	window.__jarvisImmersive = true;

	const ROUTES = ["jarvis-chat", "jarvis-onboarding", "jarvis-account"];

	const CSS =
		"body.jarvis-immersive header.navbar," +
		"body.jarvis-immersive .navbar," +
		"body.jarvis-immersive .page-head{display:none!important}" +
		"body.jarvis-immersive .main-section{padding-top:0!important}";

	function ensureStyle() {
		if (document.getElementById("jarvis-immersive-style")) return;
		const s = document.createElement("style");
		s.id = "jarvis-immersive-style";
		s.textContent = CSS;
		document.head.appendChild(s);
	}

	function sync() {
		ensureStyle();
		const route = (window.frappe && frappe.get_route && frappe.get_route()) || [];
		const on = ROUTES.indexOf(route[0] || "") !== -1;
		document.body.classList.toggle("jarvis-immersive", on);
	}

	if (window.frappe && frappe.router && frappe.router.on) {
		frappe.router.on("change", sync);
	}
	$(document).on("page-change", sync);
	$(sync); // run once on ready
})();
