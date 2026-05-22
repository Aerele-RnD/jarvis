frappe.pages["jarvis-onboarding"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: "Connect to Jarvis", single_column: true });
	const dev = !!frappe.boot.developer_mode;
	if (!dev && !window.Razorpay) {
		frappe.require("https://checkout.razorpay.com/v1/checkout.js");
	}

	injectStyles();

	// ---- state -------------------------------------------------------------
	const state = { step: 1, email: "", company: "", planName: null, plans: [], busy: false };
	const esc = frappe.utils.escape_html;
	const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");
	const cycleLabel = (c) => (String(c).toLowerCase() === "annual" ? "/year" : "/month");

	const $root = $(`
		<div class="jo">
		  <div class="jo-brand">
		    <div class="jo-logo">✦</div>
		    <div class="jo-brand-name">Jarvis</div>
		    <div class="jo-brand-tag">Ask your ERP anything — in plain English.</div>
		    <ul class="jo-props">
		      <li><span class="jo-tick">✓</span> Permission-aware answers over <b>your own</b> data</li>
		      <li><span class="jo-tick">✓</span> Reads schemas, docs, lists &amp; reports — and acts, with approval</li>
		      <li><span class="jo-tick">✓</span> Your data stays on your bench; the AI runs in a managed container</li>
		      <li><span class="jo-tick">✓</span> Set up in under a minute</li>
		    </ul>
		    <div class="jo-brand-foot">A quick setup connects this site to Jarvis Cloud.</div>
		  </div>
		  <div class="jo-panel">
		    <div class="jo-steps"></div>
		    <div class="jo-body"></div>
		    <div class="jo-foot-link"></div>
		  </div>
		</div>`);
	const $bg = $(`<div class="jo-bg"><span class="jo-blob jo-blob-1"></span><span class="jo-blob jo-blob-2"></span></div>`).appendTo(page.main);
	$root.appendTo($bg);

	const $steps = $root.find(".jo-steps");
	const $body = $root.find(".jo-body");
	const $footLink = $root.find(".jo-foot-link");

	// ---- chrome ------------------------------------------------------------
	const STEP_NAMES = ["Account", "Plan", "Pay"];
	function renderSteps() {
		if (state.step > 3) { $steps.empty(); return; }
		$steps.html(STEP_NAMES.map((name, i) => {
			const n = i + 1;
			const cls = n < state.step ? "done" : n === state.step ? "active" : "";
			const line = i < STEP_NAMES.length - 1 ? `<span class="jo-step-line ${n < state.step ? "done" : ""}"></span>` : "";
			return `<span class="jo-step ${cls}"><span class="jo-step-dot">${n < state.step ? "✓" : n}</span>
				<span class="jo-step-label">${name}</span></span>${line}`;
		}).join(""));
	}

	function footLink() {
		$footLink.html(`Already connected? <a href="#" class="jo-sync">Sync your connection</a>`);
		$footLink.find(".jo-sync").on("click", (e) => {
			e.preventDefault();
			frappe.call({ method: "jarvis.onboarding.sync_connection" }).then((r) => {
				const m = r.message || {};
				if (m.synced) frappe.show_alert({ message: __("Connection synced."), indicator: "green" });
				else frappe.show_alert({ message: __("Nothing to sync yet ({0}).", [m.tenant_status || m.reason || "pending"]), indicator: "orange" });
			});
		});
	}

	// ---- steps -------------------------------------------------------------
	function go(step) { state.step = step; render(); }

	function render() {
		renderSteps();
		if (state.step === 1) return renderAccount();
		if (state.step === 2) return renderPlan();
		if (state.step === 3) return renderPay();
	}

	function renderAccount() {
		$body.html(`
			<h2 class="jo-h">Create your account</h2>
			<p class="jo-sub">We'll set up Jarvis for this site.</p>
			<label class="jo-label">Work email</label>
			<input class="jo-input" id="jo-email" type="email" placeholder="you@company.com" value="${esc(state.email)}">
			<label class="jo-label">Company</label>
			<input class="jo-input" id="jo-company" placeholder="Acme Inc." value="${esc(state.company)}">
			<div class="jo-err" id="jo-acc-err"></div>
			<div class="jo-actions">
			  <button class="jo-btn jo-btn-primary" id="jo-next">Continue →</button>
			</div>`);
		const submit = () => {
			state.email = $body.find("#jo-email").val().trim();
			state.company = $body.find("#jo-company").val().trim();
			const ok = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(state.email);
			if (!ok) return $body.find("#jo-acc-err").text("Enter a valid email address.");
			if (!state.company) return $body.find("#jo-acc-err").text("Company name is required.");
			loadPlansThen(() => go(2));
		};
		$body.find("#jo-next").on("click", submit);
		$body.find("#jo-company").on("keydown", (e) => { if (e.key === "Enter") submit(); });
		$body.find("#jo-email").focus();
	}

	function loadPlansThen(cb) {
		if (state.plans.length) return cb();
		setBusy("#jo-next", true);
		frappe.call({ method: "jarvis.onboarding.list_plans" }).then((r) => {
			state.plans = r.message || [];
			cb();
		}).catch((e) => {
			setBusy("#jo-next", false);
			$body.find("#jo-acc-err").text("Couldn't load plans: " + (e.message || e));
		});
	}

	function renderPlan() {
		if (!state.plans.length) {
			$body.html(`<div class="jo-empty">No plans are available right now. Please contact support.</div>`);
			return;
		}
		const cards = state.plans.map((p) => {
			const feats = (p.features || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
			const sel = state.planName === p.name ? "selected" : "";
			return `<div class="jo-plan ${sel}" data-plan="${esc(p.name)}">
				<div class="jo-plan-badge">✓</div>
				<div class="jo-plan-name">${esc(p.plan_name)}</div>
				<div class="jo-plan-price">${inr(p.price_inr)}<span class="jo-plan-cycle">${cycleLabel(p.billing_cycle)}</span></div>
				<ul class="jo-plan-feats">${feats.map((f) => `<li><span class="jo-tick">✓</span>${esc(f)}</li>`).join("") ||
					`<li class="jo-muted">${esc(p.billing_cycle)} plan</li>`}</ul>
			</div>`;
		}).join("");
		$body.html(`
			<h2 class="jo-h">Choose your plan</h2>
			<p class="jo-sub">Pay as you go — no auto-renewal. Extend anytime.</p>
			<div class="jo-plans">${cards}</div>
			<div class="jo-actions jo-actions-split">
			  <button class="jo-btn jo-btn-ghost" id="jo-back">← Back</button>
			  <button class="jo-btn jo-btn-primary" id="jo-next" ${state.planName ? "" : "disabled"}>Continue →</button>
			</div>`);
		$body.find(".jo-plan").on("click", function () {
			state.planName = $(this).data("plan");
			$body.find(".jo-plan").removeClass("selected");
			$(this).addClass("selected");
			$body.find("#jo-next").prop("disabled", false);
		});
		$body.find("#jo-back").on("click", () => go(1));
		$body.find("#jo-next").on("click", () => state.planName && go(3));
	}

	function renderPay() {
		const p = state.plans.find((x) => x.name === state.planName) || {};
		$body.html(`
			<h2 class="jo-h">Review &amp; ${dev ? "connect" : "pay"}</h2>
			<div class="jo-summary">
			  <div class="jo-row"><span>Email</span><b>${esc(state.email)}</b></div>
			  <div class="jo-row"><span>Company</span><b>${esc(state.company)}</b></div>
			  <div class="jo-row"><span>Plan</span><b>${esc(p.plan_name || "")}</b></div>
			  <div class="jo-row jo-row-total"><span>Due now</span><b>${inr(p.price_inr)}<span class="jo-plan-cycle">${cycleLabel(p.billing_cycle)}</span></b></div>
			</div>
			${dev ? `<div class="jo-devnote">Developer mode — payment is skipped (dev signup).</div>` : ""}
			<div class="jo-err" id="jo-pay-err"></div>
			<div class="jo-actions jo-actions-split">
			  <button class="jo-btn jo-btn-ghost" id="jo-back">← Back</button>
			  <button class="jo-btn jo-btn-primary" id="jo-pay">${dev ? "Dev signup &amp; connect" : "Sign up &amp; pay →"}</button>
			</div>`);
		$body.find("#jo-back").on("click", () => go(2));
		$body.find("#jo-pay").on("click", dev ? devOnboard : startPay);
	}

	function renderSuccess(data) {
		state.step = 4;
		renderSteps();
		$footLink.empty();
		const url = (data && data.agent_url) || "";
		$body.html(`
			<div class="jo-success">
			  <div class="jo-success-ring">✓</div>
			  <h2 class="jo-h">You're connected!</h2>
			  <p class="jo-sub">Jarvis is set up for <b>${esc(state.company)}</b>. ${url ? "Your agent is ready." : "Your container is being prepared — it'll be ready shortly."}</p>
			  <div class="jo-actions">
			    <button class="jo-btn jo-btn-primary" id="jo-chat">Open Jarvis chat →</button>
			  </div>
			</div>`);
		$body.find("#jo-chat").on("click", () => frappe.set_route("jarvis-chat"));
	}

	// ---- actions -----------------------------------------------------------
	function startPay() {
		setBusy("#jo-pay", true);
		frappe.call({ method: "jarvis.onboarding.start_signup", args: { email: state.email, company: state.company, plan: state.planName } })
			.then((r) => openCheckout(r.message || {}))
			.catch((e) => payErr(e));
	}

	function openCheckout(d) {
		setBusy("#jo-pay", false);
		const rz = new Razorpay({
			key: d.razorpay_key_id,
			order_id: d.razorpay_order_id,
			name: "Jarvis",
			description: "Jarvis subscription",
			handler: (res) => {
				setBusy("#jo-pay", true);
				frappe.call({
					method: "jarvis.onboarding.finish_payment",
					args: { payload: { razorpay_payment_id: res.razorpay_payment_id, razorpay_order_id: res.razorpay_order_id, razorpay_signature: res.razorpay_signature } },
				}).then((rr) => renderSuccess(rr.message)).catch((e) => payErr(e));
			},
			modal: { ondismiss: () => setBusy("#jo-pay", false) },
		});
		rz.open();
	}

	function devOnboard() {
		setBusy("#jo-pay", true);
		frappe.call({ method: "jarvis.onboarding.dev_onboard", args: { email: state.email, company: state.company, plan: state.planName } })
			.then((r) => renderSuccess(r.message)).catch((e) => payErr(e));
	}

	function payErr(e) {
		setBusy("#jo-pay", false);
		$body.find("#jo-pay-err").text(e.message || "Something went wrong. Please try again.");
	}

	function setBusy(sel, on) {
		const $b = $body.find(sel);
		if (on) { $b.prop("disabled", true).attr("data-label", $b.html()).html(`<span class="jo-spin"></span> Working…`); }
		else if ($b.attr("data-label")) { $b.prop("disabled", false).html($b.attr("data-label")); }
	}

	// ---- boot --------------------------------------------------------------
	footLink();
	render();

	function injectStyles() {
		if (document.getElementById("jo-styles")) return;
		const css = `
		.jo-bg{position:relative;display:flex;align-items:center;justify-content:center;overflow:hidden;
			min-height:calc(100vh - 160px);margin:-15px -15px 0;padding:40px 20px;background:var(--bg-color);
			background:radial-gradient(120% 120% at 50% 0%, color-mix(in srgb, var(--primary,#4a47e5) 8%, var(--bg-color)) 0%, var(--bg-color) 60%)}
		.jo-blob{position:absolute;border-radius:50%;filter:blur(70px);opacity:.28;pointer-events:none;z-index:0}
		.jo-blob-1{width:380px;height:380px;background:var(--primary,#4a47e5);top:-90px;left:-60px}
		.jo-blob-2{width:340px;height:340px;background:#7c3aed;bottom:-110px;right:-40px}
		.jo{position:relative;z-index:1;display:flex;gap:0;width:100%;max-width:980px;margin:0 auto;border:1px solid var(--border-color);
			border-radius:var(--border-radius-lg,14px);overflow:hidden;box-shadow:0 20px 50px -20px rgba(20,20,50,.45),var(--shadow-md);background:var(--card-bg)}
		.jo-brand{flex:0 0 40%;padding:36px 32px;color:#fff;
			background:linear-gradient(160deg,var(--primary,#4a47e5) 0%,#6d28d9 100%);display:flex;flex-direction:column}
		.jo-logo{font-size:34px;line-height:1}
		.jo-brand-name{font-size:30px;font-weight:700;margin-top:10px;letter-spacing:-.5px}
		.jo-brand-tag{font-size:15px;opacity:.92;margin-top:6px;line-height:1.45}
		.jo-props{list-style:none;padding:0;margin:28px 0 0}
		.jo-props li{display:flex;gap:10px;align-items:flex-start;font-size:13.5px;line-height:1.5;margin-bottom:14px;opacity:.97}
		.jo-brand .jo-tick{color:#fff;background:rgba(255,255,255,.22);border-radius:50%;width:18px;height:18px;
			display:inline-flex;align-items:center;justify-content:center;font-size:11px;flex:0 0 18px;margin-top:1px}
		.jo-brand-foot{margin-top:auto;padding-top:24px;font-size:12px;opacity:.8}
		.jo-panel{flex:1;padding:34px 36px;min-width:0}
		.jo-steps{display:flex;align-items:center;margin-bottom:26px}
		.jo-step{display:flex;align-items:center;gap:8px;color:var(--text-muted)}
		.jo-step-dot{width:26px;height:26px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;
			font-size:12px;font-weight:600;border:1.5px solid var(--border-color);background:var(--card-bg)}
		.jo-step-label{font-size:12.5px;font-weight:500}
		.jo-step.active{color:var(--text-color)}
		.jo-step.active .jo-step-dot{border-color:var(--primary,#4a47e5);color:var(--primary,#4a47e5)}
		.jo-step.done{color:var(--text-color)}
		.jo-step.done .jo-step-dot{background:var(--primary,#4a47e5);border-color:var(--primary,#4a47e5);color:#fff}
		.jo-step-line{flex:1;height:2px;background:var(--border-color);margin:0 10px}
		.jo-step-line.done{background:var(--primary,#4a47e5)}
		.jo-h{font-size:21px;font-weight:700;margin:0 0 4px;color:var(--text-color)}
		.jo-sub{font-size:13.5px;color:var(--text-muted);margin:0 0 22px}
		.jo-label{display:block;font-size:12.5px;font-weight:600;color:var(--text-color);margin:14px 0 6px}
		.jo-input{width:100%;padding:10px 12px;font-size:14px;border:1px solid var(--border-color);
			border-radius:var(--border-radius,8px);background:var(--control-bg,var(--bg-color));color:var(--text-color)}
		.jo-input:focus{outline:none;border-color:var(--primary,#4a47e5);box-shadow:0 0 0 2px rgba(74,71,229,.18)}
		.jo-plans{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:8px}
		.jo-plan{position:relative;border:1.5px solid var(--border-color);border-radius:12px;padding:16px 14px;cursor:pointer;
			transition:border-color .15s,box-shadow .15s,transform .1s;background:var(--card-bg)}
		.jo-plan:hover{border-color:var(--primary,#4a47e5);transform:translateY(-1px)}
		.jo-plan.selected{border-color:var(--primary,#4a47e5);box-shadow:0 0 0 2px rgba(74,71,229,.18)}
		.jo-plan-badge{position:absolute;top:12px;right:12px;width:20px;height:20px;border-radius:50%;background:var(--primary,#4a47e5);
			color:#fff;font-size:12px;display:none;align-items:center;justify-content:center}
		.jo-plan.selected .jo-plan-badge{display:inline-flex}
		.jo-plan-name{font-size:13px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.4px}
		.jo-plan-price{font-size:24px;font-weight:700;color:var(--text-color);margin:6px 0 10px}
		.jo-plan-cycle{font-size:12px;font-weight:500;color:var(--text-muted);margin-left:2px}
		.jo-plan-feats{list-style:none;padding:0;margin:0}
		.jo-plan-feats li{display:flex;gap:7px;font-size:12.5px;color:var(--text-color);line-height:1.5;margin-bottom:6px}
		.jo-plan-feats .jo-tick{color:var(--primary,#4a47e5);font-size:11px}
		.jo-muted,.jo-empty{color:var(--text-muted)} .jo-empty{padding:20px 0}
		.jo-summary{border:1px solid var(--border-color);border-radius:10px;overflow:hidden}
		.jo-row{display:flex;justify-content:space-between;padding:12px 16px;font-size:13.5px;color:var(--text-muted);border-bottom:1px solid var(--border-color)}
		.jo-row b{color:var(--text-color)} .jo-row:last-child{border-bottom:0}
		.jo-row-total{background:var(--bg-color);font-size:15px} .jo-row-total b{font-size:18px}
		.jo-devnote{margin-top:14px;font-size:12.5px;color:var(--text-muted);background:var(--bg-color);padding:10px 12px;border-radius:8px}
		.jo-actions{margin-top:24px;display:flex} .jo-actions-split{justify-content:space-between}
		.jo-actions:not(.jo-actions-split){justify-content:flex-end}
		.jo-btn{padding:10px 20px;font-size:14px;font-weight:600;border-radius:var(--border-radius,8px);border:1px solid transparent;cursor:pointer}
		.jo-btn-primary{background:var(--primary,#4a47e5);color:#fff}
		.jo-btn-primary:hover{filter:brightness(1.06)} .jo-btn-primary:disabled{opacity:.5;cursor:not-allowed}
		.jo-btn-ghost{background:transparent;border-color:var(--border-color);color:var(--text-color)}
		.jo-err{color:var(--red-500,#e24c4c);font-size:12.5px;margin-top:10px;min-height:1px}
		.jo-foot-link{margin-top:18px;text-align:center;font-size:12.5px;color:var(--text-muted)}
		.jo-success{text-align:center;padding:18px 0}
		.jo-success-ring{width:64px;height:64px;border-radius:50%;background:rgba(46,189,89,.14);color:var(--green-600,#28a745);
			font-size:30px;display:flex;align-items:center;justify-content:center;margin:0 auto 16px}
		.jo-success .jo-actions{justify-content:center}
		.jo-spin{display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,.5);border-top-color:#fff;
			border-radius:50%;animation:jo-spin .6s linear infinite;vertical-align:-1px}
		@keyframes jo-spin{to{transform:rotate(360deg)}}
		@media(max-width:760px){.jo-bg{min-height:0;padding:20px 8px}.jo{flex-direction:column;margin:0}.jo-brand{flex-basis:auto}.jo-panel{padding:26px 22px}}`;
		$(`<style id="jo-styles">${css}</style>`).appendTo(document.head);
	}
};
