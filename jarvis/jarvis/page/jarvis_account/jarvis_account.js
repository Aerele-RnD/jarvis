frappe.pages["jarvis-account"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: "My Jarvis Account", single_column: true });
	if (!window.Razorpay) {
		frappe.require("https://checkout.razorpay.com/v1/checkout.js");
	}

	injectStyles();

	const esc = frappe.utils.escape_html;
	const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");
	const cycleLabel = (c) => (String(c).toLowerCase() === "annual" ? "/year" : "/month");

	// LLM provider defaults — mirror the onboarding wizard's PROVIDER_DEFAULTS
	// so the section behaves identically there and here.
	const PROVIDER_DEFAULTS = {
		"Anthropic":          { model: "claude-sonnet-4-6",                 baseUrl: "https://api.anthropic.com" },
		"OpenAI":             { model: "gpt-4o",                            baseUrl: "https://api.openai.com/v1" },
		"Google Gemini":      { model: "gemini-1.5-pro",                    baseUrl: "https://generativelanguage.googleapis.com" },
		"Mistral":            { model: "mistral-large-latest",              baseUrl: "https://api.mistral.ai/v1" },
		"Groq":               { model: "llama-3.3-70b-versatile",           baseUrl: "https://api.groq.com/openai/v1" },
		"Together AI":        { model: "meta-llama/Llama-3.3-70B-Instruct-Turbo", baseUrl: "https://api.together.xyz/v1" },
		"DeepSeek":           { model: "deepseek-chat",                     baseUrl: "https://api.deepseek.com" },
		"Moonshot (Kimi)":    { model: "kimi-k2.6",                         baseUrl: "https://api.moonshot.ai/v1" },
		"OpenRouter":         { model: "anthropic/claude-sonnet-4-6",       baseUrl: "https://openrouter.ai/api/v1" },
		"Ollama (local)":     { model: "llama3",                            baseUrl: "http://host.docker.internal:11434/v1" },
		"vLLM (local)":       { model: "",                                  baseUrl: "" },
		"OpenAI-Compatible":  { model: "",                                  baseUrl: "" },
	};
	const PROVIDERS = Object.keys(PROVIDER_DEFAULTS);

	// Subscription states that allow LLM credential changes. The others all
	// imply "service is paused" so the form is read-only.
	const EDITABLE_STATES = new Set(["Active", "Cancelled"]);

	const $root = $(`
		<div class="ja">
		  <div class="ja-brand">
		    <div class="ja-logo">✦</div>
		    <div class="ja-brand-name">Jarvis</div>
		    <div class="ja-brand-tag">Your AI workspace for ERPNext.</div>
		    <div class="ja-brand-foot">Manage your plan, credentials, and billing here.</div>
		  </div>
		  <div class="ja-panel">
		    <div class="ja-body"></div>
		  </div>
		</div>`);
	const $bg = $(`<div class="ja-bg"></div>`).appendTo(page.main);
	$root.appendTo($bg);
	const $body = $root.find(".ja-body");

	// ---- state -------------------------------------------------------------
	let account = null;       // payload from get_account
	let settingsLocal = null; // local Jarvis Settings LLM fields snapshot

	// ---- boot --------------------------------------------------------------
	loadInitial();

	function loadInitial() {
		$body.html(`<div class="ja-loading">Loading your account…</div>`);
		frappe.call({ method: "jarvis.account.is_onboarded" })
			.then((r) => {
				if (!r.message || !r.message.onboarded) {
					// Not onboarded — wizard owns this customer.
					window.location.assign("/app/jarvis-onboarding");
					return;
				}
				return Promise.all([
					frappe.call({ method: "jarvis.account.get_account" }),
					frappe.db.get_doc("Jarvis Settings"),
				]).then(([acc, settings]) => {
					account = (acc && acc.message) || {};
					settingsLocal = settings || {};
					render();
				});
			})
			.catch((e) => {
				$body.html(`<div class="ja-err">Couldn't load account info.
					${esc(e.message || "")}
					<button class="ja-btn ja-btn-ghost" id="ja-retry">Retry</button></div>`);
				$body.find("#ja-retry").on("click", loadInitial);
			});
	}

	function render() {
		const sub = account.subscription_status || "none";
		const editable = EDITABLE_STATES.has(sub);
		$body.html(`
			${renderPlanSection()}
			${renderSubscriptionCard()}
			${renderLlmSection(editable)}
			${renderBillingSection()}
		`);
		bindLlm(editable);
		bindSubscriptionCard();
		bindBilling();
	}

	// ---- LLM subscription card (only shown when llm_auth_mode === "oauth") --
	// REV-2: bench keeps only provider + auth_mode; the OAuth blob lives in
	// auth-profiles.json on the container. Connected-email and refresh
	// timestamps are not surfaced bench-side anymore.
	function renderSubscriptionCard() {
		if (settingsLocal.llm_auth_mode !== "oauth") return "";
		const provider = settingsLocal.llm_provider || "—";
		const model = settingsLocal.llm_model || "—";
		return `<div class="ja-card">
			<div class="ja-card-head">
				<h2 class="ja-h">LLM subscription</h2>
				<span class="ja-pill ja-pill-ok">${esc(provider)}</span>
			</div>
			<table class="ja-kv">
				<tr><td>Provider</td><td>${esc(provider)}</td></tr>
				<tr><td>Model</td><td>${esc(model)}</td></tr>
			</table>
			<p class="ja-sub">Refresh and account state live inside your Jarvis container. If chat starts failing, click Re-authorize to mint fresh tokens.</p>
			<div class="ja-actions">
				<button class="ja-btn ja-btn-ghost" id="ja-sub-disconnect">Disconnect</button>
				<button class="ja-btn ja-btn-primary" id="ja-sub-reauth">Re-authorize</button>
			</div>
		</div>`;
	}

	function bindSubscriptionCard() {
		if (settingsLocal.llm_auth_mode !== "oauth") return;
		$body.find("#ja-sub-disconnect").on("click", () => {
			if (!confirm("Disconnect the LLM subscription? Jarvis chat will stop working until you reconnect.")) return;
			frappe.call({ method: "jarvis.oauth.api.disconnect" }).then((r) => {
				const m = r.message || {};
				if (m.ok) {
					frappe.show_alert({ message: "Disconnected.", indicator: "orange" });
					loadInitial();  // refresh the page state
				} else {
					frappe.show_alert({ message: (m.error && m.error.message) || "Disconnect failed.", indicator: "red" });
				}
			});
		});
		$body.find("#ja-sub-reauth").on("click", () => {
			// Send the user back to the onboarding wizard so they can re-run
			// the helper-script sign-in (REV-2). Step 4 detects existing
			// auth_mode=oauth and pre-selects the subscription path.
			window.location.assign("/app/jarvis-onboarding");
		});
	}

	// ---- plan & validity section ------------------------------------------
	function renderPlanSection() {
		const sub = account.subscription_status || "none";
		const plan = account.plan || {};
		if (!plan || !plan.name) {
			return `<div class="ja-card">
				<h2 class="ja-h">No plan</h2>
				<p class="ja-sub">You don't have an active subscription yet.</p>
			</div>`;
		}
		const banner = renderPlanBanner(sub);
		return `<div class="ja-card">
			<div class="ja-card-head">
				<div>
					<div class="ja-eyebrow">Plan</div>
					<h2 class="ja-h">${esc(plan.plan_name || plan.name)}</h2>
					<div class="ja-plan-meta">${inr(plan.price_inr)} <span class="jo-plan-cycle">${cycleLabel(plan.billing_cycle)}</span></div>
				</div>
				${renderStatusPill(sub)}
			</div>
			${banner}
		</div>`;
	}

	function renderStatusPill(sub) {
		const tone = {
			"Active": "ok", "Cancelled": "warn", "Past Due": "warn",
			"Expired": "bad", "Pending Payment": "warn",
		}[sub] || "muted";
		return `<span class="ja-pill ja-pill-${tone}">${esc(sub)}</span>`;
	}

	function renderPlanBanner(sub) {
		const end = account.current_period_end ? frappe.datetime.str_to_user(account.current_period_end) : "";
		const days = account.days_remaining || 0;
		switch (sub) {
			case "Active":
				return `<div class="ja-banner ja-banner-ok">Renews on <b>${esc(end)}</b> · ${days} day${days === 1 ? "" : "s"} left.</div>`;
			case "Cancelled":
				return `<div class="ja-banner ja-banner-warn">Cancelled · runs until <b>${esc(end)}</b>.</div>`;
			case "Past Due":
				return `<div class="ja-banner ja-banner-warn">Plan past due — expired on <b>${esc(end)}</b>. Reactivate to resume service.</div>`;
			case "Expired":
				return `<div class="ja-banner ja-banner-bad">Plan expired on <b>${esc(end)}</b>. Reactivate to resume service.</div>`;
			case "Pending Payment":
				return `<div class="ja-banner ja-banner-warn">Payment incomplete · finish to activate.</div>`;
			default:
				return "";
		}
	}

	// ---- LLM credentials section ------------------------------------------
	function renderLlmSection(editable) {
		const provider = settingsLocal.llm_provider || "Anthropic";
		const model = settingsLocal.llm_model || (PROVIDER_DEFAULTS[provider] || {}).model || "";
		const base = settingsLocal.llm_base_url || (PROVIDER_DEFAULTS[provider] || {}).baseUrl || "";
		const sync = settingsLocal.last_sync_status || "";
		const dis = editable ? "" : "disabled";
		const tip = editable ? "" : `title="Reactivate your plan to update LLM credentials"`;
		const sel = PROVIDERS.map((p) => `<option value="${esc(p)}" ${p === provider ? "selected" : ""}>${esc(p)}</option>`).join("");
		return `<div class="ja-card" ${tip}>
			<div class="ja-eyebrow">AI provider</div>
			<h2 class="ja-h">LLM Credentials</h2>
			<p class="ja-sub">Your API key is sent directly to the provider — Jarvis only relays prompts.</p>
			<div class="ja-row2">
				<div class="ja-field">
					<label>Provider</label>
					<select class="ja-input" id="ja-prov" ${dis}>${sel}</select>
				</div>
				<div class="ja-field">
					<label>Model</label>
					<input class="ja-input" id="ja-model" value="${esc(model)}" ${dis}>
				</div>
			</div>
			<div class="ja-row2">
				<div class="ja-field">
					<label>API Key</label>
					<div class="ja-pwd">
						<input class="ja-input" id="ja-key" type="password" placeholder="${settingsLocal.llm_api_key ? "•••••••• (unchanged)" : "Enter your API key"}" ${dis}>
						<button type="button" class="ja-pwd-toggle" id="ja-key-eye" aria-label="Show key" ${dis}>
							<svg class="ja-eye-on" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
							<svg class="ja-eye-off" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 19c-7 0-10-7-10-7a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 10 7 10 7a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
						</button>
					</div>
				</div>
				<div class="ja-field">
					<label>Base URL <span class="ja-hint-inline">(optional)</span></label>
					<input class="ja-input" id="ja-base" value="${esc(base)}" ${dis}>
				</div>
			</div>
			<div class="ja-actions">
				<button class="ja-btn ja-btn-primary" id="ja-llm-save" ${dis}>Save credentials</button>
				<span class="ja-llm-status">${sync ? "Last sync: " + esc(sync) : ""}</span>
			</div>
			<div class="ja-err" id="ja-llm-err"></div>
		</div>`;
	}

	function bindLlm(editable) {
		if (!editable) return;
		$body.find("#ja-key-eye").on("click", function () {
			const $btn = $(this);
			$btn.toggleClass("shown");
			const shown = $btn.hasClass("shown");
			$body.find("#ja-key").attr("type", shown ? "text" : "password");
			$btn.attr("aria-label", shown ? "Hide key" : "Show key");
		});
		const $prov = $body.find("#ja-prov");
		$prov.on("change", () => {
			const p = $prov.val();
			const d = PROVIDER_DEFAULTS[p] || {};
			$body.find("#ja-model").val(d.model || "");
			$body.find("#ja-base").val(d.baseUrl || "");
		});
		$body.find("#ja-llm-save").on("click", () => {
			const provider = $prov.val();
			const model = $body.find("#ja-model").val().trim();
			const key = $body.find("#ja-key").val().trim();
			const base = $body.find("#ja-base").val().trim();
			if (!provider || !model) {
				return $body.find("#ja-llm-err").text("Provider and model are required.");
			}
			if (!key && !settingsLocal.llm_api_key) {
				return $body.find("#ja-llm-err").text("API key is required.");
			}
			$body.find("#ja-llm-err").text("");
			setBusy("#ja-llm-save", true);
			frappe.call({
				method: "jarvis.onboarding.save_llm_creds",
				args: { provider, model, api_key: key || "", base_url: base },
			}).then((r) => {
				setBusy("#ja-llm-save", false);
				const status = (r.message && r.message.last_sync_status) || "";
				$body.find(".ja-llm-status").text(status ? "Last sync: " + status : "Saved.");
				settingsLocal.llm_provider = provider;
				settingsLocal.llm_model = model;
				settingsLocal.llm_base_url = base;
				settingsLocal.llm_api_key = key || settingsLocal.llm_api_key;
				settingsLocal.last_sync_status = status;
				// Clear the entered key from the input now that it's persisted.
				$body.find("#ja-key").val("");
			}).catch((e) => {
				setBusy("#ja-llm-save", false);
				$body.find("#ja-llm-err").text(e.message || "Save failed.");
			});
		});
	}

	// ---- billing section --------------------------------------------------
	function renderBillingSection() {
		const sub = account.subscription_status || "none";
		const upgrade = (account.upgrade_plans || []).length > 0;
		const ctaPrimary = primaryCta(sub);
		const ctaSecondary = secondaryCta(sub, upgrade);
		return `<div class="ja-card">
			<div class="ja-eyebrow">Billing</div>
			<h2 class="ja-h">${esc(ctaPrimary.heading)}</h2>
			<p class="ja-sub">${esc(ctaPrimary.subtitle)}</p>
			<div class="ja-actions">
				${ctaPrimary ? `<button class="ja-btn ja-btn-primary" id="ja-cta-primary" data-action="${ctaPrimary.action}">${esc(ctaPrimary.label)}</button>` : ""}
				${ctaSecondary ? `<button class="ja-btn ja-btn-ghost" id="ja-cta-secondary" data-action="${ctaSecondary.action}">${esc(ctaSecondary.label)}</button>` : ""}
			</div>
			<div class="ja-err" id="ja-billing-err"></div>
		</div>`;
	}

	function primaryCta(sub) {
		const upgrade = (account.upgrade_plans || []).length > 0;
		switch (sub) {
			case "Active":
				return upgrade
					? { action: "upgrade", label: "Upgrade plan",
						heading: "Want more capacity?", subtitle: "Move to a higher plan — you only pay the prorated difference for the remaining period." }
					: { action: "renew", label: "Renew now",
						heading: "Renew early", subtitle: "Add another billing cycle to your current plan." };
			case "Cancelled":
				return { action: "renew", label: "Resume / Renew",
						 heading: "Resume your plan", subtitle: "Pay now to keep service running past the current period end." };
			case "Past Due":
			case "Expired":
				return { action: "renew", label: "Reactivate",
						 heading: "Reactivate your plan", subtitle: "Pay now to restore service and bring your container back online." };
			case "Pending Payment":
				return { action: "renew", label: "Complete payment",
						 heading: "Finish signing up", subtitle: "Complete payment to activate your plan." };
			default:
				return { action: "renew", label: "Subscribe", heading: "Subscribe", subtitle: "" };
		}
	}

	function secondaryCta(sub, hasUpgrade) {
		if (sub === "Active" && hasUpgrade) return { action: "renew", label: "Renew now" };
		if (sub === "Cancelled" && hasUpgrade) return { action: "upgrade", label: "Upgrade plan" };
		return null;
	}

	function bindBilling() {
		$body.find("#ja-cta-primary, #ja-cta-secondary").on("click", function () {
			const action = $(this).data("action");
			if (action === "upgrade") return openUpgradeModal();
			if (action === "renew") return startRenew();
		});
	}

	// ---- renew flow -------------------------------------------------------
	function startRenew() {
		setBusy("#ja-cta-primary", true);
		setBusy("#ja-cta-secondary", true);
		frappe.call({ method: "jarvis.onboarding.renew" })
			.then((r) => {
				setBusy("#ja-cta-primary", false);
				setBusy("#ja-cta-secondary", false);
				const data = (r.message && r.message.data) || r.message || {};
				openCheckout(data, /*upgrade=*/false);
			}).catch((e) => {
				setBusy("#ja-cta-primary", false);
				setBusy("#ja-cta-secondary", false);
				$body.find("#ja-billing-err").text(e.message || "Couldn't start payment.");
			});
	}

	// ---- upgrade flow + modal --------------------------------------------
	function openUpgradeModal() {
		const plans = account.upgrade_plans || [];
		const cards = plans.map((p) => `
			<div class="ja-up-card" data-plan="${esc(p.name)}">
				<div class="ja-up-card-head">
					<div class="ja-up-card-name">${esc(p.plan_name || p.name)}</div>
					<div class="ja-up-card-price">${inr(p.price_inr)} <span class="jo-plan-cycle">${cycleLabel(p.billing_cycle)}</span></div>
				</div>
				<div class="ja-up-card-prorate" data-plan-prorate="${esc(p.name)}">Calculating prorated amount…</div>
				<button class="ja-btn ja-btn-primary ja-up-pick" data-plan="${esc(p.name)}" disabled>Loading…</button>
			</div>`).join("");
		const html = `<div class="ja-modal-bg">
			<div class="ja-modal">
				<div class="ja-modal-head">
					<h2 class="ja-h">Choose an upgrade</h2>
					<button class="ja-modal-close" id="ja-modal-close">✕</button>
				</div>
				<p class="ja-sub">You only pay the prorated difference for the days remaining in your current billing period.</p>
				<div class="ja-up-list">${cards || `<div class="ja-empty">No upgrade plans available.</div>`}</div>
				<div class="ja-err" id="ja-up-err"></div>
			</div>
		</div>`;
		const $m = $(html).appendTo(document.body);
		$m.find("#ja-modal-close, .ja-modal-bg").on("click", function (e) {
			if (e.target === this) $m.remove();
		});
		// Fetch prorated amount per plan in parallel.
		plans.forEach((p) => {
			frappe.call({ method: "jarvis.account.preview_upgrade", args: { target_plan: p.name } })
				.then((r) => {
					const d = (r.message && r.message.data) || r.message || {};
					$m.find(`[data-plan-prorate="${p.name}"]`).text(`Pay ${inr(d.prorated_inr)} now`);
					$m.find(`.ja-up-pick[data-plan="${p.name}"]`)
						.text(`Pay ${inr(d.prorated_inr)}`).prop("disabled", false)
						.on("click", () => startUpgrade(p.name, $m));
				}).catch((e) => {
					$m.find(`[data-plan-prorate="${p.name}"]`).text(e.message || "Couldn't compute amount.");
				});
		});
	}

	function startUpgrade(target_plan, $modal) {
		const $btn = $modal.find(`.ja-up-pick[data-plan="${target_plan}"]`);
		setBusy($btn, true);
		frappe.call({ method: "jarvis.account.start_upgrade", args: { target_plan } })
			.then((r) => {
				setBusy($btn, false);
				const data = (r.message && r.message.data) || r.message || {};
				$modal.remove();
				openCheckout(data, /*upgrade=*/true);
			}).catch((e) => {
				setBusy($btn, false);
				$modal.find("#ja-up-err").text(e.message || "Couldn't start upgrade.");
			});
	}

	// ---- Razorpay Checkout (shared) ---------------------------------------
	function openCheckout(handles, isUpgrade) {
		const opts = {
			key: handles.razorpay_key_id,
			amount: Math.round((handles.amount_inr || 0) * 100),
			currency: "INR",
			order_id: handles.razorpay_order_id,
			name: "Jarvis",
			description: isUpgrade ? "Plan upgrade" : "Subscription payment",
			handler: function (res) {
				confirmAndRefresh({
					razorpay_payment_id: res.razorpay_payment_id,
					razorpay_order_id: res.razorpay_order_id,
					razorpay_signature: res.razorpay_signature,
				});
			},
		};
		new Razorpay(opts).open();
	}

	// finish_payment + self-healing fallback (idempotent confirm + polling)
	function confirmAndRefresh(payload) {
		showOverlay("Finalizing your payment…");
		frappe.call({ method: "jarvis.onboarding.finish_payment", args: { payload } })
			.then(() => { hideOverlay(); loadInitial(); })
			.catch(() => pollForApplied());
	}

	function pollForApplied() {
		showOverlay("Payment received — finalizing your account…");
		const before = JSON.stringify({
			plan: (account.plan || {}).name || "",
			end: account.current_period_end || "",
			status: account.subscription_status || "",
		});
		let elapsed = 0;
		const tick = setInterval(() => {
			elapsed += 3;
			frappe.call({ method: "jarvis.account.get_account" }).then((r) => {
				const a = (r && r.message) || {};
				const now = JSON.stringify({
					plan: (a.plan || {}).name || "",
					end: a.current_period_end || "",
					status: a.subscription_status || "",
				});
				if (now !== before) {
					clearInterval(tick); hideOverlay(); loadInitial();
				} else if (elapsed >= 30) {
					clearInterval(tick); hideOverlay();
					frappe.msgprint({
						title: "Plan update pending",
						message: "Your payment was received. The page should update within a minute — refresh to view, or contact support if it doesn't.",
						indicator: "blue",
					});
				}
			}).catch(() => {
				if (elapsed >= 30) {
					clearInterval(tick); hideOverlay();
				}
			});
		}, 3000);
	}

	// ---- small helpers ----------------------------------------------------
	function setBusy(sel, on) {
		const $b = typeof sel === "string" ? $body.find(sel) : sel;
		if (on) { $b.prop("disabled", true).attr("data-label", $b.html()).html(`<span class="ja-spin"></span> Working…`); }
		else if ($b.attr("data-label")) { $b.prop("disabled", false).html($b.attr("data-label")); }
	}

	function showOverlay(text) {
		hideOverlay();
		$(`<div class="ja-overlay"><div class="ja-overlay-card"><span class="ja-spin"></span> ${esc(text)}</div></div>`).appendTo(document.body);
	}
	function hideOverlay() { $(".ja-overlay").remove(); }

	function injectStyles() {
		if (document.getElementById("ja-styles")) return;
		const css = `
		.ja-bg{position:fixed;inset:0;z-index:1;display:flex;align-items:flex-start;justify-content:center;
			overflow:hidden auto;padding:48px 20px;background-color:var(--bg-color)}
		.ja-bg::before{content:"";position:absolute;inset:-25%;z-index:0;will-change:transform;
			animation:ja-aurora 26s ease-in-out infinite alternate;
			background-image:
			  radial-gradient(at 16% 20%, color-mix(in srgb, var(--jarvis-primary) 26%, transparent) 0, transparent 46%),
			  radial-gradient(at 84% 16%, color-mix(in srgb, var(--jarvis-primary-dark) 22%, transparent) 0, transparent 46%),
			  radial-gradient(at 78% 84%, color-mix(in srgb, var(--jarvis-primary-light) 18%, transparent) 0, transparent 44%),
			  radial-gradient(at 22% 82%, color-mix(in srgb, var(--jarvis-primary) 16%, transparent) 0, transparent 46%)}
		@keyframes ja-aurora{0%{transform:translate3d(0,0,0) scale(1) rotate(0deg)}
			50%{transform:translate3d(2.5%,-2%,0) scale(1.08) rotate(1.2deg)}
			100%{transform:translate3d(-2%,2.5%,0) scale(1.05) rotate(-1.2deg)}}
		@media(prefers-reduced-motion:reduce){.ja-bg::before{animation:none}}
		.ja{position:relative;z-index:1;display:flex;gap:0;width:100%;max-width:1080px;margin:auto;border:1px solid var(--border-color);
			border-radius:var(--border-radius-lg,14px);overflow:hidden;box-shadow:0 20px 50px -20px rgba(20,20,50,.45),var(--shadow-md);background:var(--card-bg)}
		.ja-brand{flex:0 0 34%;padding:36px 32px;color:#fff;background:linear-gradient(160deg,var(--jarvis-primary-light) 0%,var(--jarvis-primary-dark) 100%);display:flex;flex-direction:column}
		.ja-logo{font-size:34px;line-height:1}
		.ja-brand-name{font-size:30px;font-weight:700;margin-top:10px;letter-spacing:-.5px}
		.ja-brand-tag{font-size:15px;opacity:.92;margin-top:6px;line-height:1.45}
		.ja-brand-foot{margin-top:auto;padding-top:24px;font-size:12px;opacity:.8}
		.ja-panel{flex:1;padding:34px 36px;min-width:0;display:flex;flex-direction:column;gap:18px}
		.ja-loading,.ja-empty{color:var(--text-muted);padding:18px 0}
		.ja-card{border:1px solid var(--border-color);border-radius:12px;padding:20px;background:var(--card-bg)}
		.ja-card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
		.ja-eyebrow{font-size:11.5px;letter-spacing:.6px;font-weight:600;color:var(--text-muted);text-transform:uppercase}
		.ja-h{font-size:20px;font-weight:700;margin:2px 0 4px;color:var(--text-color)}
		.ja-sub{font-size:13.5px;color:var(--text-muted);margin:0 0 14px}
		.ja-plan-meta{font-size:14px;color:var(--text-color);margin-top:4px}
		.ja-pill{padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600;letter-spacing:.3px;border:1px solid transparent;white-space:nowrap}
		.ja-pill-ok{background:rgba(46,189,89,.12);color:var(--green-700,#1f8d3a);border-color:rgba(46,189,89,.25)}
		.ja-pill-warn{background:rgba(245,159,0,.14);color:var(--yellow-700,#a06200);border-color:rgba(245,159,0,.28)}
		.ja-pill-bad{background:rgba(226,76,76,.12);color:var(--red-600,#c0392b);border-color:rgba(226,76,76,.25)}
		.ja-pill-muted{background:var(--bg-color);color:var(--text-muted);border-color:var(--border-color)}
		.ja-banner{margin-top:14px;padding:10px 12px;border-radius:8px;font-size:13px}
		.ja-banner-ok{background:rgba(46,189,89,.08);color:var(--text-color)}
		.ja-banner-warn{background:rgba(245,159,0,.10);color:var(--text-color)}
		.ja-banner-bad{background:rgba(226,76,76,.10);color:var(--text-color)}
		.ja-row2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
		.ja-field{margin-bottom:6px}
		.ja-field label{display:block;font-size:12.5px;font-weight:600;color:var(--text-color);margin-bottom:6px}
		.ja-input{width:100%;padding:10px 12px;font-size:14px;border:1px solid var(--border-color);border-radius:var(--border-radius,8px);background:var(--control-bg,var(--bg-color));color:var(--text-color)}
		.ja-input:focus{outline:none;border-color:var(--jarvis-primary);box-shadow:0 0 0 2px var(--jarvis-primary-faint)}
		.ja-input:disabled{opacity:.6;cursor:not-allowed}
		.ja-pwd{position:relative}
		.ja-pwd .ja-input{padding-right:38px}
		.ja-pwd-toggle{position:absolute;top:50%;right:6px;transform:translateY(-50%);background:transparent;border:0;cursor:pointer;
			color:var(--text-muted);padding:6px;line-height:0;border-radius:6px}
		.ja-pwd-toggle:hover{color:var(--text-color);background:var(--bg-color)}
		.ja-pwd-toggle:disabled{opacity:.4;cursor:not-allowed}
		.ja-pwd-toggle .ja-eye-off{display:none}
		.ja-pwd-toggle.shown .ja-eye-on{display:none}
		.ja-pwd-toggle.shown .ja-eye-off{display:inline}
		.ja-actions{margin-top:14px;display:flex;align-items:center;gap:10px}
		.ja-btn{padding:9px 18px;font-size:14px;font-weight:600;border-radius:var(--border-radius,8px);border:1px solid transparent;cursor:pointer}
		.ja-btn-primary{background:var(--jarvis-primary);color:#fff}
		.ja-btn-primary:hover{filter:brightness(1.06)}
		.ja-btn-primary:disabled{opacity:.5;cursor:not-allowed}
		.ja-btn-ghost{background:transparent;border-color:var(--border-color);color:var(--text-color)}
		.ja-btn-ghost:hover{border-color:var(--jarvis-primary);color:var(--jarvis-primary)}
		.ja-err{color:var(--red-500,#e24c4c);font-size:12.5px;margin-top:8px;min-height:1px}
		.ja-llm-status{color:var(--text-muted);font-size:12.5px;margin-left:8px}
		.ja-spin{display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,.5);border-top-color:#fff;border-radius:50%;animation:ja-spin .6s linear infinite;vertical-align:-1px}
		@keyframes ja-spin{to{transform:rotate(360deg)}}
		.ja-modal-bg{position:fixed;inset:0;background:rgba(20,20,40,.55);z-index:1000;display:flex;align-items:center;justify-content:center;padding:20px}
		.ja-modal{background:var(--card-bg);border-radius:14px;max-width:600px;width:100%;padding:28px;box-shadow:0 20px 60px -20px rgba(0,0,0,.5)}
		.ja-modal-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px}
		.ja-modal-close{background:transparent;border:0;font-size:18px;cursor:pointer;color:var(--text-muted)}
		.ja-up-list{display:flex;flex-direction:column;gap:10px;margin-top:12px}
		.ja-up-card{border:1px solid var(--border-color);border-radius:10px;padding:14px 16px}
		.ja-up-card-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}
		.ja-up-card-name{font-size:14px;font-weight:600;color:var(--text-color)}
		.ja-up-card-price{font-size:16px;font-weight:700;color:var(--text-color)}
		.ja-up-card-prorate{font-size:13px;color:var(--text-muted);margin-bottom:10px}
		.ja-overlay{position:fixed;inset:0;z-index:2000;background:rgba(20,20,40,.45);display:flex;align-items:center;justify-content:center}
		.ja-overlay-card{background:var(--card-bg);padding:18px 22px;border-radius:10px;font-size:14px;color:var(--text-color);box-shadow:0 12px 40px -12px rgba(0,0,0,.4)}
		.ja-overlay .ja-spin{border-color:var(--jarvis-primary-faint);border-top-color:var(--jarvis-primary)}
		.ja-kv{width:100%;border-collapse:collapse;margin:8px 0 16px}
		.ja-kv td{padding:6px 0;font-size:13.5px}
		.ja-kv td:first-child{color:var(--text-muted);width:140px}
		@media(max-width:760px){.ja{flex-direction:column}.ja-brand{flex-basis:auto}.ja-panel{padding:24px 22px}.ja-row2{grid-template-columns:1fr}}
		`;
		$(`<style id="ja-styles">${css}</style>`).appendTo(document.head);
	}
};
