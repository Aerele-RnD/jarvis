// Not-onboarded desk banner — nudges a System Manager who lands in the
// Frappe desk (bookmark, admin default landing) but hasn't finished the
// Jarvis setup wizard yet, toward the SPA wizard at /jarvis/onboarding.
//
// Reads `frappe.boot.jarvis_onboarded` (set in jarvis.boot.set_jarvis_boot).
// Dismissal is per-tab-session only (sessionStorage) — the banner comes
// back on the next fresh session until the wizard is actually finished.
//
// Loaded on every Desk page via hooks.app_include_js, same as
// jarvis_immersive.bundle.js / jarvis_widget.bundle.js.

(function () {
	if (window.__jarvisOnboardingBanner) return;
	window.__jarvisOnboardingBanner = true;

	var DISMISS_KEY = "jarvis_onboarding_banner_dismissed";
	var BANNER_ID = "jarvis-onboarding-banner";

	// The legacy desk onboarding page — no point nagging a user who's
	// already mid-setup there.
	var HIDE_ON_ROUTES = ["jarvis-onboarding"];

	function shouldShow() {
		if (!window.frappe || !frappe.boot) return false;
		if (frappe.boot.jarvis_onboarded !== false) return false;
		if (!frappe.user || !frappe.user.has_role || !frappe.user.has_role("System Manager")) return false;
		try {
			if (sessionStorage.getItem(DISMISS_KEY)) return false;
		} catch (e) {
			// sessionStorage unavailable (privacy mode etc.) - fall through
			// and show the banner rather than silently hide it forever.
		}
		var route = (frappe.get_route && frappe.get_route()) || [];
		if (HIDE_ON_ROUTES.indexOf(route[0] || "") !== -1) return false;
		return true;
	}

	function dismiss() {
		try {
			sessionStorage.setItem(DISMISS_KEY, "1");
		} catch (e) {
			/* ignore */
		}
		remove();
	}

	function remove() {
		var el = document.getElementById(BANNER_ID);
		if (el && el.parentNode) el.parentNode.removeChild(el);
	}

	function inject() {
		if (document.getElementById(BANNER_ID)) return; // guard: already injected

		var bar = document.createElement("div");
		bar.id = BANNER_ID;
		bar.style.cssText =
			"position:relative;display:flex;align-items:center;justify-content:center;" +
			"gap:12px;flex-wrap:wrap;padding:8px 40px;background:#5b21b6;color:#fff;" +
			"font-size:13px;line-height:1.4;text-align:center;z-index:1000;";

		var text = document.createElement("span");
		text.textContent = "Finish setting up Jarvis";
		bar.appendChild(text);

		var link = document.createElement("a");
		link.href = "/jarvis/onboarding";
		link.textContent = "Set up now →";
		link.style.cssText = "color:#fff;font-weight:600;text-decoration:underline;";
		bar.appendChild(link);

		var close = document.createElement("button");
		close.type = "button";
		close.setAttribute("aria-label", "Dismiss");
		close.textContent = "×";
		close.style.cssText =
			"position:absolute;right:12px;top:50%;transform:translateY(-50%);" +
			"background:transparent;border:0;color:#fff;font-size:18px;line-height:1;" +
			"cursor:pointer;padding:0 4px;";
		close.addEventListener("click", dismiss);
		bar.appendChild(close);

		document.body.insertBefore(bar, document.body.firstChild);
	}

	function sync() {
		if (shouldShow()) {
			inject();
		} else {
			remove();
		}
	}

	function start() {
		if (!window.frappe) return;
		sync();
		if (frappe.router && frappe.router.on) frappe.router.on("change", sync);
	}

	if (window.frappe && window.frappe.router) {
		start();
	} else if (window.$) {
		$(start);
	} else {
		document.addEventListener("DOMContentLoaded", start);
	}
})();
