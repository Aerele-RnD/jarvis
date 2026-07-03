// Not-onboarded desk nudge — a chat popup that pops out of the Jarvis chat
// launcher (bottom-right of the Desk), styled like Jarvis is messaging the
// user to finish setup and start easing their ERP workflows. Replaces the old
// top banner with a friendlier, on-brand "Jarvis is chatting" bubble thread.
//
// Reads `frappe.boot.jarvis_onboarded` (set in jarvis.boot.set_jarvis_boot).
// Shows only for a not-onboarded System Manager; dismissal is per-tab-session
// (sessionStorage) so it returns next fresh session until setup is finished.
// Loaded on every Desk page via hooks.app_include_js.

(function () {
	if (window.__jarvisOnboardingBanner) return;
	window.__jarvisOnboardingBanner = true;

	var DISMISS_KEY = "jarvis_onboarding_nudge_dismissed";
	var NUDGE_ID = "jarvis-onboarding-nudge";
	var STYLE_ID = "jarvis-onboarding-nudge-style";
	var BLUE = "#2563eb";
	// No point nagging a user already mid-setup on the legacy desk page.
	var HIDE_ON_ROUTES = ["jarvis-onboarding"];

	function shouldShow() {
		if (!window.frappe || !frappe.boot) return false;
		if (frappe.boot.jarvis_onboarded !== false) return false;
		if (!frappe.user || !frappe.user.has_role || !frappe.user.has_role("System Manager")) return false;
		try {
			if (sessionStorage.getItem(DISMISS_KEY)) return false;
		} catch (e) {
			// sessionStorage unavailable (privacy mode etc.) — show it anyway.
		}
		var route = (frappe.get_route && frappe.get_route()) || [];
		if (HIDE_ON_ROUTES.indexOf(route[0] || "") !== -1) return false;
		return true;
	}

	function dismiss() {
		try { sessionStorage.setItem(DISMISS_KEY, "1"); } catch (e) { /* ignore */ }
		remove();
	}

	function remove() {
		var el = document.getElementById(NUDGE_ID);
		if (el && el.parentNode) el.parentNode.removeChild(el);
	}

	function ensureStyles() {
		if (document.getElementById(STYLE_ID)) return;
		var st = document.createElement("style");
		st.id = STYLE_ID;
		st.textContent =
			"@keyframes jvNudgeIn{from{opacity:0;transform:translateY(8px) scale(.98)}to{opacity:1;transform:none}}" +
			"#" + NUDGE_ID + "{position:fixed;right:24px;bottom:92px;z-index:1050;width:328px;max-width:calc(100vw - 40px);" +
			"font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;display:flex;flex-direction:column;gap:8px;}" +
			"#" + NUDGE_ID + " .jvn-row{display:flex;align-items:flex-end;gap:8px;opacity:0;animation:jvNudgeIn .32s cubic-bezier(.2,.7,.3,1) forwards;}" +
			"#" + NUDGE_ID + " .jvn-row.r1{animation-delay:.05s;}" +
			"#" + NUDGE_ID + " .jvn-row.r2{animation-delay:.42s;}" +   // staggered — feels like a 2nd message
			"#" + NUDGE_ID + " .jvn-av{width:24px;height:24px;flex:none;border-radius:7px;background:" + BLUE + ";display:flex;align-items:center;justify-content:center;box-shadow:0 1px 2px rgba(37,99,235,.35);}" +
			"#" + NUDGE_ID + " .jvn-bubble{position:relative;background:#fff;border:1px solid #e6e6ee;border-radius:14px;padding:10px 13px;font-size:13px;line-height:1.45;color:#20232e;box-shadow:0 6px 22px -8px rgba(20,20,40,.22);}" +
			"#" + NUDGE_ID + " .jvn-name{font-size:11px;font-weight:600;color:#8a8aa0;margin-bottom:3px;}" +
			"#" + NUDGE_ID + " .jvn-btn{display:inline-flex;align-items:center;gap:6px;margin-top:10px;background:" + BLUE + ";color:#fff;border:0;border-radius:8px;padding:7px 13px;font-size:12.5px;font-weight:600;text-decoration:none;cursor:pointer;}" +
			"#" + NUDGE_ID + " .jvn-x{position:absolute;top:-9px;right:-9px;width:22px;height:22px;border-radius:50%;background:#fff;border:1px solid #e6e6ee;color:#6b6b80;font-size:13px;line-height:1;cursor:pointer;box-shadow:0 2px 6px rgba(20,20,40,.14);display:flex;align-items:center;justify-content:center;}" +
			"#" + NUDGE_ID + " .jvn-tail{align-self:flex-end;margin:-2px 16px 0 0;width:14px;height:14px;background:#fff;border-right:1px solid #e6e6ee;border-bottom:1px solid #e6e6ee;transform:rotate(45deg);opacity:0;animation:jvNudgeIn .32s ease .5s forwards;}";
		document.head.appendChild(st);
	}

	function avatar() {
		var a = document.createElement("div");
		a.className = "jvn-av";
		// Build the Jarvis star mark via SVG DOM (no innerHTML) — XSS-safe by construction.
		var NS = "http://www.w3.org/2000/svg";
		var svg = document.createElementNS(NS, "svg");
		svg.setAttribute("width", "14"); svg.setAttribute("height", "14");
		svg.setAttribute("viewBox", "0 0 24 24"); svg.setAttribute("fill", "#fff");
		var path = document.createElementNS(NS, "path");
		path.setAttribute("d", "M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z");
		svg.appendChild(path);
		a.appendChild(svg);
		return a;
	}

	function bubbleRow(cls, buildBubble) {
		var row = document.createElement("div");
		row.className = "jvn-row " + cls;
		row.appendChild(avatar());
		row.appendChild(buildBubble());
		return row;
	}

	function inject() {
		if (document.getElementById(NUDGE_ID)) return;
		ensureStyles();

		var wrap = document.createElement("div");
		wrap.id = NUDGE_ID;
		wrap.setAttribute("role", "complementary");
		wrap.setAttribute("aria-label", "Set up Jarvis");

		// Bubble 1 — greeting.
		wrap.appendChild(bubbleRow("r1", function () {
			var b = document.createElement("div");
			b.className = "jvn-bubble";
			var n = document.createElement("div"); n.className = "jvn-name"; n.textContent = "Jarvis"; b.appendChild(n);
			var t = document.createElement("div"); t.textContent = "Hey 👋 I'm Jarvis."; b.appendChild(t);
			return b;
		}));

		// Bubble 2 — pitch + CTA + dismiss.
		wrap.appendChild(bubbleRow("r2", function () {
			var b = document.createElement("div");
			b.className = "jvn-bubble";

			var x = document.createElement("button");
			x.type = "button"; x.className = "jvn-x"; x.setAttribute("aria-label", "Dismiss");
			x.textContent = "×";
			x.addEventListener("click", dismiss);
			b.appendChild(x);

			var t = document.createElement("div");
			t.textContent = "Set me up and I'll handle the ERP busywork — draft quotes, chase invoices, pull reports, and automate your workflows.";
			b.appendChild(t);

			var cta = document.createElement("a");
			cta.className = "jvn-btn";
			cta.href = "/jarvis/onboarding";
			cta.textContent = "Set up Jarvis →";
			b.appendChild(cta);
			return b;
		}));

		// Tail pointing down toward the chat launcher.
		var tail = document.createElement("div");
		tail.className = "jvn-tail";
		wrap.appendChild(tail);

		document.body.appendChild(wrap);
	}

	function sync() {
		if (shouldShow()) inject(); else remove();
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
