frappe.pages["jarvis-onboarding"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: "Connect to Jarvis", single_column: true });
	const dev = !!frappe.boot.developer_mode;
	if (!dev && !window.Razorpay) {
		frappe.require("https://checkout.razorpay.com/v1/checkout.js");
	}

	injectStyles();

	// ---- state -------------------------------------------------------------
	const state = {
		step: 1, email: "", company: "", planName: null, plans: [], busy: false,
		// step 4 inputs — API key path
		llmProvider: "Anthropic", llmModel: "", llmApiKey: "", llmBaseUrl: "",
		// step 4 inputs — chat subscription path
		authMode: "api_key", // "api_key" | "subscription"
		subProvider: "OpenAI",
		subNonce: null,
		subOneLiner: null,
		subExpiresAt: null,  // wall-clock ms (10 min nonce TTL)
		subPollTimer: null,
		subConnectedEmail: null,
		// passed through to step 5 (success)
		successData: null,
	};

	// Providers that support the chat-subscription OAuth device flow.
	// Mirrors jarvis.oauth.providers.PROVIDER_OAUTH_MAP — keep in sync.
	const SUBSCRIPTION_PROVIDERS = ["OpenAI", "Google Gemini"];

	// Default model + baseUrl per provider, surfaced as autofilled hints on step 4.
	// Customers can override both in the form (and later in Jarvis Settings).
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
	const $bg = $(`<div class="jo-bg"></div>`).appendTo(page.main);
	$root.appendTo($bg);

	const $steps = $root.find(".jo-steps");
	const $body = $root.find(".jo-body");
	const $footLink = $root.find(".jo-foot-link");

	// ---- chrome ------------------------------------------------------------
	const STEP_NAMES = ["Account", "Plan", "Pay", "Connect AI"];
	function renderSteps() {
		if (state.step > STEP_NAMES.length) { $steps.empty(); return; }
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
		if (state.step === 4) return renderLlm();
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

	function renderLlm() {
		// Defaults arrive lazy: only fill model/baseUrl if the customer hasn't typed.
		const d = PROVIDER_DEFAULTS[state.llmProvider] || { model: "", baseUrl: "" };
		if (!state.llmModel) state.llmModel = d.model;
		if (!state.llmBaseUrl) state.llmBaseUrl = d.baseUrl;
		const providers = Object.keys(PROVIDER_DEFAULTS).map(
			(p) => `<option value="${esc(p)}" ${p === state.llmProvider ? "selected" : ""}>${esc(p)}</option>`
		).join("");
		const authModeHtml = `
			<div class="jo-field">
			  <label>How will Jarvis talk to your LLM?</label>
			  <div class="jo-radio-group">
			    <label class="jo-radio"><input type="radio" name="jo-auth-mode" value="api_key" ${state.authMode === "api_key" ? "checked" : ""}/> <span>Paste an API key</span></label>
			    <label class="jo-radio"><input type="radio" name="jo-auth-mode" value="subscription" ${state.authMode === "subscription" ? "checked" : ""}/> <span>Sign in with my chat subscription</span></label>
			  </div>
			</div>`;
		if (state.authMode === "subscription") {
			$body.html(`
				<h2 class="jo-h">Connect your AI</h2>
				<p class="jo-sub">Sign in once with your existing ChatGPT Plus or Gemini Advanced
				   account — no API key, no extra cost. Jarvis will use your subscription quota.</p>
				${authModeHtml}
				${renderSubscriptionPanel()}
				<div class="jo-err" id="jo-llm-err"></div>`);
			wireAuthModeRadio();
			wireSubscriptionPanel();
			return;
		}
		$body.html(`
			<h2 class="jo-h">Connect your AI</h2>
			<p class="jo-sub">Pick which model Jarvis should use and paste your API key.
			   You can change this anytime in Jarvis Settings.</p>
			${authModeHtml}
			<div class="jo-field">
			  <label>Provider</label>
			  <select id="jo-llm-provider" class="jo-input">${providers}</select>
			</div>
			<div class="jo-field">
			  <label>Model</label>
			  <input id="jo-llm-model" type="text" class="jo-input" value="${esc(state.llmModel)}" placeholder="e.g. claude-sonnet-4-6"/>
			</div>
			<div class="jo-field">
			  <label>API key</label>
			  <div class="jo-pwd">
			    <input id="jo-llm-key" type="password" class="jo-input" value="${esc(state.llmApiKey)}" placeholder="sk-..." autocomplete="off"/>
			    <button type="button" class="jo-pwd-toggle" id="jo-llm-key-eye" aria-label="Show key">
			      <svg class="jo-eye-on" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
			      <svg class="jo-eye-off" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 19c-7 0-10-7-10-7a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 10 7 10 7a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
			    </button>
			  </div>
			  <div class="jo-hint">Stored encrypted; only your agent container ever sees the plaintext.</div>
			</div>
			<div class="jo-field">
			  <label>Base URL <span class="jo-hint-inline">(advanced)</span></label>
			  <input id="jo-llm-base" type="text" class="jo-input" value="${esc(state.llmBaseUrl)}" placeholder="${esc(d.baseUrl || "https://...")}"/>
			</div>
			<div class="jo-err" id="jo-llm-err"></div>
			<div class="jo-actions jo-actions-split">
			  <button class="jo-btn jo-btn-ghost" id="jo-llm-skip">Skip for now</button>
			  <button class="jo-btn jo-btn-primary" id="jo-llm-save">Save &amp; finish →</button>
			</div>`);

		$body.find("#jo-llm-provider").on("change", (e) => {
			state.llmProvider = e.target.value;
			// Reset model/baseUrl so the new provider's defaults take effect.
			state.llmModel = "";
			state.llmBaseUrl = "";
			renderLlm();
		});
		$body.find("#jo-llm-model").on("input", (e) => { state.llmModel = e.target.value; });
		$body.find("#jo-llm-key").on("input", (e) => { state.llmApiKey = e.target.value; });
		$body.find("#jo-llm-key-eye").on("click", function () {
			const $btn = $(this);
			$btn.toggleClass("shown");
			const shown = $btn.hasClass("shown");
			$body.find("#jo-llm-key").attr("type", shown ? "text" : "password");
			$btn.attr("aria-label", shown ? "Hide key" : "Show key");
		});
		$body.find("#jo-llm-base").on("input", (e) => { state.llmBaseUrl = e.target.value; });
		$body.find("#jo-llm-skip").on("click", () => renderSuccess(state.successData || {}));
		$body.find("#jo-llm-save").on("click", saveLlm);
		wireAuthModeRadio();
	}

	function wireAuthModeRadio() {
		$body.find('input[name="jo-auth-mode"]').on("change", function () {
			state.authMode = this.value;
			// Reset subscription state when switching back to api_key
			if (state.authMode === "api_key") cancelSubscriptionFlow();
			renderLlm();
		});
	}

	function renderSubscriptionPanel() {
		const provOptions = SUBSCRIPTION_PROVIDERS.map(
			(p) => `<option value="${esc(p)}" ${p === state.subProvider ? "selected" : ""}>${esc(p)}</option>`
		).join("");
		if (state.subConnectedEmail) {
			return `
				<div class="jo-sub-connected">
				  <div class="jo-success-ring">✓</div>
				  <div>Connected as <strong>${esc(state.subConnectedEmail)}</strong></div>
				  <div class="jo-actions jo-actions-split" style="margin-top:18px">
				    <button class="jo-btn jo-btn-ghost" id="jo-sub-disconnect-local">Sign in as someone else</button>
				    <button class="jo-btn jo-btn-primary" id="jo-sub-continue">Continue →</button>
				  </div>
				</div>`;
		}
		if (state.subOneLiner) {
			const minsLeft = Math.max(0, Math.floor((state.subExpiresAt - Date.now()) / 60000));
			return `
				<div class="jo-field">
				  <label>Run this on your computer</label>
				  <div class="jo-one-liner-wrap">
				    <pre class="jo-one-liner">${esc(state.subOneLiner)}</pre>
				    <button type="button" class="jo-copy-btn" id="jo-sub-copy" aria-label="Copy" title="Copy">
				      <svg class="jo-copy-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
				      <svg class="jo-check-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
				    </button>
				  </div>
				  <div class="jo-hint">Paste it into Terminal (or PowerShell). The script opens your browser, you sign in to ${esc(state.subProvider)}, and Jarvis picks up the result automatically. Link valid for ~${minsLeft} minute${minsLeft === 1 ? "" : "s"}.</div>
				</div>
				<div class="jo-actions jo-actions-split">
				  <button class="jo-btn jo-btn-ghost" id="jo-sub-share">Send to colleague</button>
				  <button class="jo-btn jo-btn-ghost" id="jo-sub-regen">Generate new one-liner</button>
				</div>
				<div class="jo-hint" style="margin-top:14px">⠹ Waiting for sign-in… <a href="#" id="jo-sub-why">Why my computer?</a></div>`;
		}
		return `
			<div class="jo-field">
			  <label>Provider</label>
			  <select id="jo-sub-provider" class="jo-input">${provOptions}</select>
			</div>
			<div class="jo-hint">A short code will appear; sign in with your subscription account at that URL.
			   You can share the code with a colleague (e.g. the budget owner) if they should authorize on their device.</div>
			<div class="jo-actions">
			  <button class="jo-btn jo-btn-primary" id="jo-sub-signin">Sign in with <span id="jo-sub-provider-label">${esc(state.subProvider)}</span></button>
			</div>`;
	}

	function wireSubscriptionPanel() {
		$body.find("#jo-sub-provider").on("change", (e) => {
			state.subProvider = e.target.value;
			renderLlm();
		});
		$body.find("#jo-sub-signin").on("click", startSubscriptionSignin);
		$body.find("#jo-sub-regen").on("click", () => { cancelSubscriptionFlow(); startSubscriptionSignin(); });
		$body.find("#jo-sub-share").on("click", shareSubscriptionOneLiner);
		$body.find("#jo-sub-copy").on("click", function () {
			if (!state.subOneLiner) return;
			const $btn = $(this);
			navigator.clipboard.writeText(state.subOneLiner).then(() => {
				$btn.addClass("copied");
				setTimeout(() => $btn.removeClass("copied"), 1400);
			});
		});
		$body.find("#jo-sub-why").on("click", (e) => {
			e.preventDefault();
			frappe.msgprint({
				title: "Why your computer?",
				message: "Signing in to ChatGPT requires opening a browser. " +
				         "The script opens it on the same machine it runs on, " +
				         "then sends the result back to Jarvis automatically. " +
				         "Run it on the computer you're using right now."
			});
		});
		$body.find("#jo-sub-disconnect-local").on("click", () => {
			cancelSubscriptionFlow();
			state.subConnectedEmail = null;
			renderLlm();
		});
		$body.find("#jo-sub-continue").on("click", commitSubscriptionSignin);
	}

	function startSubscriptionSignin() {
		const $err = $body.find("#jo-llm-err");
		$err.text("");
		setBusy("#jo-sub-signin", true);
		frappe.call({
			method: "jarvis.oauth.api.begin_codex_signin",
			args: { provider: state.subProvider },
		}).then((r) => {
			setBusy("#jo-sub-signin", false);
			const m = r.message || {};
			if (!m.ok) {
				$err.text((m.error && m.error.message) || "Couldn't start sign-in. Please try again.");
				return;
			}
			const d = m.data;
			state.subNonce = d.nonce;
			state.subOneLiner = d.one_liner;
			state.subExpiresAt = Date.now() + 600 * 1000;  // 10-min TTL
			renderLlm();
			schedulePoll(2);  // poll every 2s
		}).catch((e) => {
			setBusy("#jo-sub-signin", false);
			$err.text(e.message || "Couldn't reach Jarvis. Try again in a moment.");
		});
	}

	function schedulePoll(intervalSec) {
		cancelPollTimer();
		state.subPollTimer = setTimeout(() => pollOnce(intervalSec), intervalSec * 1000);
	}

	function pollOnce(intervalSec) {
		if (!state.subNonce) return;
		frappe.call({
			method: "jarvis.oauth.api.poll_signin",
			args: { nonce: state.subNonce },
		}).then((r) => {
			const m = r.message || {};
			if (!m.ok) {
				const err = m.error || {};
				$body.find("#jo-llm-err").text(err.message || "Sign-in failed.");
				cancelSubscriptionFlow();
				renderLlm();
				return;
			}
			const data = m.data || {};
			if (data.status === "connected") {
				state.subConnectedEmail = data.account_email || "(unknown)";
				cancelPollTimer();
				state.subOneLiner = null;
				renderLlm();
				return;
			}
			schedulePoll(intervalSec);
		}).catch(() => {
			schedulePoll(intervalSec);
		});
	}

	function cancelPollTimer() {
		if (state.subPollTimer) { clearTimeout(state.subPollTimer); state.subPollTimer = null; }
	}

	function cancelSubscriptionFlow() {
		cancelPollTimer();
		state.subNonce = null;
		state.subOneLiner = null;
		state.subExpiresAt = null;
	}

	function shareSubscriptionOneLiner() {
		const recipient = prompt("Send the sign-in command to which email address?");
		if (!recipient) return;
		frappe.call({
			method: "jarvis.oauth.api.share_signin",
			args: { nonce: state.subNonce, recipient_email: recipient },
		}).then((r) => {
			const m = r.message || {};
			if (m.ok) {
				frappe.show_alert({ message: "Sent to " + recipient, indicator: "green" });
			} else {
				const err = m.error || {};
				frappe.show_alert({ message: err.message || "Couldn't send", indicator: "red" });
			}
		}).catch((e) => {
			frappe.show_alert({ message: e.message || "Couldn't send", indicator: "red" });
		});
	}

	function commitSubscriptionSignin() {
		setBusy("#jo-sub-continue", true);
		frappe.call({
			method: "jarvis.oauth.api.commit_signin",
			args: { nonce: state.subNonce },
		}).then((r) => {
			setBusy("#jo-sub-continue", false);
			const m = r.message || {};
			if (!m.ok) {
				$body.find("#jo-llm-err").text(
					(m.error && m.error.message) || "Couldn't finalize sign-in."
				);
				return;
			}
			state.subNonce = null;
			renderSuccess(state.successData || {}, "ok (subscription)");
		}).catch((e) => {
			setBusy("#jo-sub-continue", false);
			$body.find("#jo-llm-err").text(e.message || "Couldn't reach Jarvis.");
		});
	}

	function saveLlm() {
		const $err = $body.find("#jo-llm-err");
		$err.text("");
		if (!state.llmProvider || !state.llmModel.trim() || !state.llmApiKey.trim()) {
			$err.text("Provider, model, and API key are all required.");
			return;
		}
		setBusy("#jo-llm-save", true);
		frappe.call({
			method: "jarvis.onboarding.save_llm_creds",
			args: {
				provider: state.llmProvider,
				model: state.llmModel.trim(),
				api_key: state.llmApiKey,
				base_url: state.llmBaseUrl.trim(),
			},
		}).then((r) => {
			setBusy("#jo-llm-save", false);
			const m = r.message || {};
			renderSuccess(state.successData || {}, m.last_sync_status || "");
		}).catch((e) => {
			setBusy("#jo-llm-save", false);
			$err.text(e.message || "Couldn't save LLM settings. Please try again.");
		});
	}

	function renderSuccess(data, syncStatus) {
		state.step = 5;
		renderSteps();
		$footLink.empty();
		const url = (data && data.agent_url) || "";
		const sync = (syncStatus || "").trim();
		const syncOk = sync.startsWith("ok");
		const syncSkippedNoCreds = !sync;  // came in via "Skip for now"
		let agentLine;
		if (!url) {
			agentLine = "Your container is being prepared — it'll be ready shortly.";
		} else if (syncOk) {
			agentLine = "Your agent is ready.";
		} else if (syncSkippedNoCreds) {
			agentLine = "Your agent is ready — finish connecting your AI in Jarvis Settings to start chatting.";
		} else {
			agentLine = `Your agent is set up, but the AI connection didn't sync just now (<i>${esc(sync)}</i>). Open Jarvis Settings → Force Resync to retry.`;
		}
		$body.html(`
			<div class="jo-success">
			  <div class="jo-success-ring">✓</div>
			  <h2 class="jo-h">You're connected!</h2>
			  <p class="jo-sub">Jarvis is set up for <b>${esc(state.company)}</b>. ${agentLine}</p>
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
				}).then((rr) => { state.successData = rr.message; go(4); }).catch((e) => payErr(e));
			},
			modal: { ondismiss: () => setBusy("#jo-pay", false) },
		});
		rz.open();
	}

	function devOnboard() {
		setBusy("#jo-pay", true);
		frappe.call({ method: "jarvis.onboarding.dev_onboard", args: { email: state.email, company: state.company, plan: state.planName } })
			.then((r) => { state.successData = r.message; setBusy("#jo-pay", false); go(4); }).catch((e) => payErr(e));
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
	bootRender();

	function bootRender() {
		// Returning customers who already finished signup get the completion
		// card instead of the create-account form. On RPC failure (e.g. site
		// just spun up, scheduler not running), fall back to the wizard so
		// the page is never stuck.
		frappe.call({ method: "jarvis.account.is_onboarded" })
			.then((r) => {
				if (r && r.message && r.message.onboarded) renderCompletionCard();
				else render();
			})
			.catch(() => render());
	}

	function renderCompletionCard() {
		$steps.empty();
		$footLink.empty();
		$body.html(`
			<div class="jo-success">
				<div class="jo-success-ring">✓</div>
				<h2 class="jo-h">You're all set up</h2>
				<p class="jo-sub">Your Jarvis account is connected. Manage your plan, billing, and LLM credentials from My Account.</p>
				<div class="jo-actions">
					<button class="jo-btn jo-btn-primary" id="jo-go-account">Go to My Account →</button>
				</div>
			</div>`);
		$body.find("#jo-go-account").on("click", () => {
			window.location.assign("/app/jarvis-account");
		});
	}

	function injectStyles() {
		if (document.getElementById("jo-styles")) return;
		const css = `
		.jo-bg{position:fixed;inset:0;z-index:1;display:flex;align-items:center;justify-content:center;
			overflow:hidden auto;padding:48px 20px;background-color:var(--bg-color)}
		.jo-bg::before{content:"";position:absolute;inset:-25%;z-index:0;will-change:transform;
			animation:jo-aurora 26s ease-in-out infinite alternate;
			background-image:
			  radial-gradient(at 16% 20%, color-mix(in srgb, var(--jarvis-primary) 26%, transparent) 0, transparent 46%),
			  radial-gradient(at 84% 16%, color-mix(in srgb, var(--jarvis-primary-dark) 22%, transparent) 0, transparent 46%),
			  radial-gradient(at 78% 84%, color-mix(in srgb, var(--jarvis-primary-light) 18%, transparent) 0, transparent 44%),
			  radial-gradient(at 22% 82%, color-mix(in srgb, var(--jarvis-primary) 16%, transparent) 0, transparent 46%)}
		@keyframes jo-aurora{0%{transform:translate3d(0,0,0) scale(1) rotate(0deg)}
			50%{transform:translate3d(2.5%,-2%,0) scale(1.08) rotate(1.2deg)}
			100%{transform:translate3d(-2%,2.5%,0) scale(1.05) rotate(-1.2deg)}}
		@media(prefers-reduced-motion:reduce){.jo-bg::before{animation:none}}
		.jo{position:relative;z-index:1;display:flex;gap:0;width:100%;max-width:980px;margin:auto;border:1px solid var(--border-color);
			border-radius:var(--border-radius-lg,14px);overflow:hidden;box-shadow:0 20px 50px -20px rgba(20,20,50,.45),var(--shadow-md);background:var(--card-bg)}
		.jo-brand{flex:0 0 40%;padding:36px 32px;color:#fff;
			background:linear-gradient(160deg,var(--jarvis-primary-light) 0%,var(--jarvis-primary-dark) 100%);display:flex;flex-direction:column}
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
		.jo-step.active .jo-step-dot{border-color:var(--jarvis-primary);color:var(--jarvis-primary)}
		.jo-step.done{color:var(--text-color)}
		.jo-step.done .jo-step-dot{background:var(--jarvis-primary);border-color:var(--jarvis-primary);color:#fff}
		.jo-step-line{flex:1;height:2px;background:var(--border-color);margin:0 10px}
		.jo-step-line.done{background:var(--jarvis-primary)}
		.jo-h{font-size:21px;font-weight:700;margin:0 0 4px;color:var(--text-color)}
		.jo-sub{font-size:13.5px;color:var(--text-muted);margin:0 0 22px}
		.jo-label{display:block;font-size:12.5px;font-weight:600;color:var(--text-color);margin:14px 0 6px}
		.jo-input{width:100%;padding:10px 12px;font-size:14px;border:1px solid var(--border-color);
			border-radius:var(--border-radius,8px);background:var(--control-bg,var(--bg-color));color:var(--text-color)}
		.jo-input:focus{outline:none;border-color:var(--jarvis-primary);box-shadow:0 0 0 2px var(--jarvis-primary-faint)}
		.jo-field{margin-bottom:14px}
		.jo-field label{display:block;font-size:12.5px;font-weight:600;color:var(--text-color);margin-bottom:6px}
		.jo-hint{font-size:11.5px;color:var(--text-muted);margin-top:4px}
		.jo-pwd{position:relative}
		.jo-pwd .jo-input{padding-right:38px}
		.jo-pwd-toggle{position:absolute;top:50%;right:6px;transform:translateY(-50%);background:transparent;border:0;cursor:pointer;
			color:var(--text-muted);padding:6px;line-height:0;border-radius:6px}
		.jo-pwd-toggle:hover{color:var(--text-color);background:var(--bg-color)}
		.jo-pwd-toggle .jo-eye-off{display:none}
		.jo-pwd-toggle.shown .jo-eye-on{display:none}
		.jo-pwd-toggle.shown .jo-eye-off{display:inline}
		.jo-hint-inline{font-weight:400;color:var(--text-muted);font-size:11.5px}
		.jo-plans{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:8px}
		.jo-plan{position:relative;border:1.5px solid var(--border-color);border-radius:12px;padding:16px 14px;cursor:pointer;
			transition:border-color .15s,box-shadow .15s,transform .1s;background:var(--card-bg)}
		.jo-plan:hover{border-color:var(--jarvis-primary);transform:translateY(-1px)}
		.jo-plan.selected{border-color:var(--jarvis-primary);box-shadow:0 0 0 2px var(--jarvis-primary-faint)}
		.jo-plan-badge{position:absolute;top:12px;right:12px;width:20px;height:20px;border-radius:50%;background:var(--jarvis-primary);
			color:#fff;font-size:12px;display:none;align-items:center;justify-content:center}
		.jo-plan.selected .jo-plan-badge{display:inline-flex}
		.jo-plan-name{font-size:13px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.4px}
		.jo-plan-price{font-size:24px;font-weight:700;color:var(--text-color);margin:6px 0 10px}
		.jo-plan-cycle{font-size:12px;font-weight:500;color:var(--text-muted);margin-left:2px}
		.jo-plan-feats{list-style:none;padding:0;margin:0}
		.jo-plan-feats li{display:flex;gap:7px;font-size:12.5px;color:var(--text-color);line-height:1.5;margin-bottom:6px}
		.jo-plan-feats .jo-tick{color:var(--jarvis-primary);font-size:11px}
		.jo-muted,.jo-empty{color:var(--text-muted)} .jo-empty{padding:20px 0}
		.jo-summary{border:1px solid var(--border-color);border-radius:10px;overflow:hidden}
		.jo-row{display:flex;justify-content:space-between;padding:12px 16px;font-size:13.5px;color:var(--text-muted);border-bottom:1px solid var(--border-color)}
		.jo-row b{color:var(--text-color)} .jo-row:last-child{border-bottom:0}
		.jo-row-total{background:var(--bg-color);font-size:15px} .jo-row-total b{font-size:18px}
		.jo-devnote{margin-top:14px;font-size:12.5px;color:var(--text-muted);background:var(--bg-color);padding:10px 12px;border-radius:8px}
		.jo-actions{margin-top:24px;display:flex} .jo-actions-split{justify-content:space-between}
		.jo-actions:not(.jo-actions-split){justify-content:flex-end}
		.jo-btn{padding:10px 20px;font-size:14px;font-weight:600;border-radius:var(--border-radius,8px);border:1px solid transparent;cursor:pointer}
		.jo-btn-primary{background:var(--jarvis-primary);color:#fff}
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
		.jo-radio-group{display:flex;flex-direction:column;gap:8px;margin-top:6px}
		.jo-radio{display:flex;align-items:center;gap:10px;cursor:pointer;padding:10px 12px;border:1px solid var(--border-color);
			border-radius:var(--border-radius,6px);transition:border-color .12s ease,background .12s ease}
		.jo-radio:hover{border-color:var(--jarvis-primary);background:var(--jarvis-primary-soft)}
		.jo-radio input[type=radio]:checked + span{font-weight:600;color:var(--jarvis-primary)}
		.jo-one-liner-wrap{position:relative}
		.jo-one-liner{font-family:'Menlo','Monaco',monospace;font-size:12px;line-height:1.5;white-space:pre-wrap;
			word-break:break-all;padding:12px 44px 12px 14px;background:var(--bg-color);border:1px solid var(--border-color);
			border-radius:8px;margin:0;color:var(--text-color)}
		.jo-copy-btn{position:absolute;top:8px;right:8px;width:28px;height:28px;display:flex;align-items:center;justify-content:center;
			background:transparent;border:1px solid var(--border-color);border-radius:6px;cursor:pointer;
			color:var(--text-muted);transition:color .12s ease,background .12s ease,border-color .12s ease}
		.jo-copy-btn:hover{color:var(--text-color);background:var(--card-bg,#fff);border-color:var(--text-muted)}
		.jo-copy-btn .jo-check-icon{display:none}
		.jo-copy-btn.copied{color:var(--green-600,#28a745);border-color:rgba(46,189,89,.4);background:rgba(46,189,89,.10)}
		.jo-copy-btn.copied .jo-copy-icon{display:none}
		.jo-copy-btn.copied .jo-check-icon{display:block}
		.jo-code-uri{font-family:'Menlo','Monaco',monospace;font-size:13px;word-break:break-all;
			padding:10px 12px;background:var(--bg-color);border:1px solid var(--border-color);border-radius:6px}
		.jo-code-uri a{color:var(--jarvis-primary)}
		.jo-code-display{font-family:'Menlo','Monaco',monospace;font-size:28px;font-weight:700;letter-spacing:3px;text-align:center;
			padding:18px;background:var(--bg-color);border:2px dashed var(--jarvis-primary);border-radius:8px;color:var(--jarvis-primary)}
		.jo-sub-connected{text-align:center;padding:18px 0}
		@media(max-width:760px){.jo-bg{padding:16px 10px}.jo{flex-direction:column;margin:auto}.jo-brand{flex-basis:auto}.jo-panel{padding:26px 22px}}`;
		$(`<style id="jo-styles">${css}</style>`).appendTo(document.head);
	}
};
