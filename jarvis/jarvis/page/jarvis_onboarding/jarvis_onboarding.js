frappe.pages["jarvis-onboarding"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: "Connect to Jarvis", single_column: true });
	// `dev` gates the dev-onboard shortcut (skip payment). Read once from
	// the bootinfo here for UX-only decisions (Razorpay script preload,
	// renderPay()'s heading + button label). This value can be STALE if
	// the operator toggles `Jarvis Settings.sandbox_mode` after page load.
	//
	// The click-time payment branch must NOT trust this value alone. See
	// the click handler in renderPay() - it queries
	// `jarvis.dev.is_dev_mode_active` at click time so we never charge a
	// customer when sandbox mode was switched on mid-session.
	//
	// Replaces the legacy `frappe.boot.developer_mode` check with the
	// per-site `Jarvis Settings.sandbox_mode` flag, exposed via
	// jarvis.boot.set_jarvis_boot. Falls back to developer_mode for one
	// release so existing dev installs aren't disrupted.
	const dev = !!(frappe.boot.jarvis_sandbox_mode || frappe.boot.developer_mode);
	if (!dev && !window.Razorpay) {
		frappe.require("https://checkout.razorpay.com/v1/checkout.js");
	}

	injectStyles();

	// ---- state -------------------------------------------------------------
	const state = {
		step: 1, email: "", company: "", planName: null, plans: [], busy: false,
		// Deployment-mode fork: null = not chosen yet (show the chooser),
		// "managed" = Aerele-hosted (the existing plan/pay/LLM flow),
		// "selfhost" = bring-your-own openclaw (URL + token + validate).
		mode: null, shUrl: "", shToken: "",
		// step 4 inputs - API key path
		llmProvider: "Anthropic", llmModel: "", llmApiKey: "", llmBaseUrl: "",
		// step 4 inputs - chat subscription path (REV-3 paste-back)
		authMode: "api_key", // "api_key" | "subscription"
		subProvider: "OpenAI",
		// Populated from defaultModels[subProvider] once bootRender
		// fetches the catalogue. Empty until then so a stale value
		// can't sneak into a paste-back signin before the canonical
		// Python set has been confirmed.
		subModel: "",
		subNonce: null,
		subAuthorizeUrl: null,   // shown to the customer in Screen 2
		subExpiresAt: null,
		// passed through to step 5 (success)
		successData: null,
		// LLM setup mode: "quick" | "preset" | "custom"
		llmMode: "quick", selectedPreset: null, presetKeys: {}, customRows: [],
	};

	// Providers + models for chat-subscription. Populated by bootRender
	// via jarvis.chat.api.get_chat_ui_settings - the canonical
	// catalogue lives in jarvis/_subscription_models.py, so the JS
	// side is a pure consumer and never drifts from the Python /
	// security allowlist (jarvis.oauth.api validates against the
	// same dict). Until the fetch lands the maps are empty and
	// renderSubscriptionPanel falls through to a "Loading…" state.
	// Punch-list "_SUBSCRIPTION_MODELS duplicated 4-5 times" from
	// the 2026-06-16 cross-repo review.
	let subscriptionModels = {};
	let defaultModels = {};
	let presetCatalog = [];

	// Default model + baseUrl per provider, surfaced as autofilled hints on step 4.
	// Customers can override both in the form (and later in Jarvis Settings).
	const PROVIDER_DEFAULTS = {
		"Anthropic":          { model: "claude-sonnet-4-6",                 baseUrl: "https://api.anthropic.com" },
		"OpenAI":             { model: "gpt-4o",                            baseUrl: "https://api.openai.com/v1" },
		"Google Gemini":      { model: "gemini-2.5-pro",                    baseUrl: "https://generativelanguage.googleapis.com" },
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
	// Stored pools may carry the provider *id* (e.g. "openai_compat") rather
	// than the dropdown *label* ("OpenAI-Compatible"). Map id -> label so a
	// row's <select> selects the right option; a value that is already a
	// label passes through unchanged. Mirrors jarvis_account.js providerLabel.
	const PROVIDER_LABEL_BY_ID = {
		anthropic: "Anthropic", openai: "OpenAI", google: "Google Gemini", mistral: "Mistral",
		groq: "Groq", together: "Together AI", deepseek: "DeepSeek", moonshot: "Moonshot (Kimi)",
		openrouter: "OpenRouter", ollama: "Ollama (local)", vllm: "vLLM (local)", openai_compat: "OpenAI-Compatible",
	};
	function providerLabel(v) {
		if (!v) return v;
		if (PROVIDER_DEFAULTS[v]) return v;   // already a label
		return PROVIDER_LABEL_BY_ID[v] || v;  // map id -> label (or keep unknown as-is)
	}
	const esc = frappe.utils.escape_html;

	// ---- model suggestions (Custom-mode <datalist>) -----------------------
	// The Custom rows bind the model field to a <datalist> so common IDs are
	// pickable while arbitrary IDs stay typeable (openai_compat / Ollama / shim
	// need custom model ids). Suggestions are sourced per provider:
	//   1) the already-loaded preset catalog (models grouped by vendor id), then
	//   2) a small static fallback for providers the catalog omits, then
	//   3) the provider's default model. Deduped, catalog-first.
	// Mirrors jarvis_account.js so both surfaces stay uniform.
	const STATIC_MODEL_SUGGESTIONS = {
		"Anthropic":         ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"],
		"OpenAI":            ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-4o"],
		"Google Gemini":     ["gemini-2.5-pro", "gemini-3.5-flash", "gemini-3.1-flash-lite"],
		"Mistral":           ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
		"Groq":              ["llama-3.3-70b-versatile"],
		"Together AI":       ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
		"DeepSeek":          ["deepseek-chat"],
		"Moonshot (Kimi)":   ["kimi-k2.6"],
		"OpenRouter":        ["anthropic/claude-sonnet-4-6", "openai/gpt-5.5"],
		"Ollama (local)":    ["qwen2.5:3b", "qwen2.5:0.5b", "llama3"],
		"OpenAI-Compatible": ["claude-sonnet-4-6", "gpt-4o", "qwen2.5:3b", "llama3"],
		// vLLM (local): no useful default → plain free-text input.
	};
	// Subscription rows suggest the upstream's chat models (keyed by upstream id).
	const SUB_MODEL_SUGGESTIONS = {
		openai: ["gpt-5.5", "gpt-5.4"],
		google: ["gemini-2.5-pro", "gemini-3.5-flash"],
	};
	// Preset-catalog vendor ids -> provider dropdown label. The catalog uses
	// "gemini"; the dropdown label is "Google Gemini" (stored id "google"), so
	// alias both to the same label. Others fall through to providerLabel.
	function catalogVendorLabel(vid) {
		if (vid === "gemini") return "Google Gemini";
		return providerLabel(vid);
	}
	// Suggested model ids for an API-key row's provider (label or id).
	function modelSuggestionsForProvider(provider) {
		const label = providerLabel(provider || "");
		const out = [];
		const push = (id) => { if (id && out.indexOf(id) === -1) out.push(id); };
		(presetCatalog || []).forEach((e) => (e.models || []).forEach((m) => {
			if (catalogVendorLabel(m.provider) === label) push(m.model);
		}));
		(STATIC_MODEL_SUGGESTIONS[label] || []).forEach(push);
		push((PROVIDER_DEFAULTS[label] || {}).model);
		return out;
	}
	// Suggested model ids for a subscription row's chosen upstream.
	function subModelSuggestions(upstream) {
		return SUB_MODEL_SUGGESTIONS[upstream] || [];
	}
	// A <datalist> of model-id suggestions. Empty list → the bound input just
	// behaves as a plain free-text field.
	function renderModelDatalist(id, suggestions) {
		const opts = (suggestions || []).map((m) => `<option value="${esc(m)}"></option>`).join("");
		return `<datalist id="${id}">${opts}</datalist>`;
	}
	const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");
	const cycleLabel = (c) => (String(c).toLowerCase() === "annual" ? "/year" : "/month");

	const $root = $(`
		<div class="jo">
		  <div class="jo-brand">
		    <div class="jo-logo">✦</div>
		    <div class="jo-brand-name">Jarvis</div>
		    <div class="jo-brand-tag">Ask your ERP anything - in plain English.</div>
		    <ul class="jo-props">
		      <li><span class="jo-tick">✓</span><span class="jo-prop-text">Permission-aware answers over <b>your own</b> data</span></li>
		      <li><span class="jo-tick">✓</span><span class="jo-prop-text">Reads schemas, docs, lists &amp; reports - and acts, with approval</span></li>
		      <li><span class="jo-tick">✓</span><span class="jo-prop-text">Your data stays on your bench; the AI runs in a managed container</span></li>
		      <li><span class="jo-tick">✓</span><span class="jo-prop-text">Set up in under a minute</span></li>
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

	// ---- helpers -----------------------------------------------------------
	// Copy text to clipboard with a graceful fallback for insecure contexts
	// (HTTP / non-localhost). Returns a Promise that resolves on success,
	// rejects on failure so callers can show honest feedback. The customer
	// can hit /jarvis-onboarding over LAN HTTP where navigator.clipboard is
	// undefined, so we must NOT call it unguarded.
	function copyTextWithFallback(text) {
		if (navigator.clipboard && window.isSecureContext) {
			return navigator.clipboard.writeText(text);
		}
		return new Promise((resolve, reject) => {
			const ta = document.createElement("textarea");
			ta.value = text;
			ta.style.position = "fixed";
			ta.style.left = "-9999px";
			ta.style.top = "0";
			document.body.appendChild(ta);
			ta.focus();
			ta.select();
			try {
				const ok = document.execCommand("copy");
				document.body.removeChild(ta);
				ok ? resolve() : reject(new Error("execCommand copy returned false"));
			} catch (e) {
				document.body.removeChild(ta);
				reject(e);
			}
		});
	}

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
				if (m.synced) {
					// Connection landed successfully - advance the wizard
					// to the completion screen instead of leaving the
					// customer staring at step 1 with a green toast.
					// Punch-list item from the 2026-06-16 review: the
					// previous shape showed "Connection synced." but
					// left the wizard at whatever step they were on,
					// which read as a dead state.
					frappe.show_alert({ message: __("Connection synced."), indicator: "green" });
					state.successData = state.successData || {};
					go(4);
				} else {
					frappe.show_alert({ message: __("Nothing to sync yet ({0}).", [m.tenant_status || m.reason || "pending"]), indicator: "orange" });
				}
			});
		});
	}

	// ---- steps -------------------------------------------------------------
	function go(step) { state.step = step; render(); }

	function render() {
		if (state.mode === null) return renderModeChoice();
		if (state.mode === "selfhost") return renderSelfHost();
		renderSteps();
		if (state.step === 1) return renderAccount();
		if (state.step === 2) return renderPlan();
		if (state.step === 3) return renderPay();
		if (state.step === 4) return renderLlm();
	}

	// ---- deployment-mode fork ---------------------------------------------
	function renderModeChoice() {
		$steps.empty();
		$footLink.empty();
		$body.html(`
			<h2 class="jo-h">How do you want to run Jarvis?</h2>
			<p class="jo-sub">Choose where the openclaw agent runs. You can switch later from My Account.</p>
			<div class="jo-modes">
			  <div class="jo-mode" data-mode="managed">
			    <div class="jo-mode-icon">☁</div>
			    <div class="jo-mode-name">Managed</div>
			    <ul class="jo-mode-feats">
			      <li><span class="jo-tick">✓</span>We host the openclaw agent for you</li>
			      <li><span class="jo-tick">✓</span>Includes the Jarvis persona + Frappe skills</li>
			      <li><span class="jo-tick">✓</span>Managed LLM proxy — pool your API keys &amp; chat subscriptions, with automatic failover</li>
			      <li><span class="jo-tick">✓</span>Simple plan &amp; billing</li>
			    </ul>
			    <button class="jo-btn jo-btn-primary jo-mode-pick">Choose →</button>
			  </div>
			  <div class="jo-mode" data-mode="selfhost">
			    <div class="jo-mode-icon">🖥</div>
			    <div class="jo-mode-name">Self-hosted</div>
			    <ul class="jo-mode-feats">
			      <li><span class="jo-tick">✓</span>Bring your own openclaw server</li>
			      <li><span class="jo-tick">✓</span>Bring your own LLM</li>
			      <li><span class="jo-tick">✓</span>Open-source · bring your own persona &amp; skills</li>
			      <li style="color:var(--red-600,#b91c1c);margin-top:8px"><span style="margin-right:4px">⚠</span>Not included: the Jarvis persona + Frappe skill packs, the managed LLM proxy (pooling &amp; failover), and managed updates &amp; support.</li>
			    </ul>
			    <button class="jo-btn jo-btn-ghost jo-mode-pick">Choose →</button>
			  </div>
			</div>`);
		$body.find('.jo-mode[data-mode="managed"] .jo-mode-pick').on("click", () => { state.mode = "managed"; go(1); });
		$body.find('.jo-mode[data-mode="selfhost"] .jo-mode-pick').on("click", () => { state.mode = "selfhost"; render(); });
	}

	function renderSelfHost() {
		$steps.empty();
		$footLink.empty();
		$body.html(`
			<h2 class="jo-h">Connect your openclaw</h2>
			<p class="jo-sub">Point Jarvis at <b>your own</b> openclaw server. Jarvis connects over HTTP
			   with a bearer token - no Aerele persona/skills. Validate first, then connect.</p>
			<div class="jo-field">
			  <label for="jo-sh-url">openclaw URL</label>
			  <input id="jo-sh-url" class="jo-input" type="text" placeholder="http://host.docker.internal:19060" value="${esc(state.shUrl)}"/>
			</div>
			<div class="jo-field">
			  <label for="jo-sh-token">Gateway token</label>
			  <input id="jo-sh-token" class="jo-input" type="password" placeholder="paste your openclaw gateway token" value="${esc(state.shToken)}" autocomplete="off"/>
			</div>
			<label class="jo-check"><input type="checkbox" id="jo-sh-stream" checked/> Stream responses token-by-token (recommended)</label>
			<label class="jo-check"><input type="checkbox" id="jo-sh-deep"/> Run deep chat test (slower — sends one message)</label>
			<div class="jo-actions" style="margin-top:12px;justify-content:flex-start">
			  <button class="jo-btn jo-btn-ghost" id="jo-sh-test">Test connection</button>
			</div>
			<div id="jo-sh-results" class="jo-sh-results"></div>
			<div class="jo-err" id="jo-sh-err"></div>
			<div class="jo-actions jo-actions-split">
			  <button class="jo-btn jo-btn-ghost" id="jo-sh-back">← Back</button>
			  <button class="jo-btn jo-btn-primary" id="jo-sh-connect">Connect →</button>
			</div>`);
		$body.find("#jo-sh-url").on("input", (e) => { state.shUrl = e.target.value; });
		$body.find("#jo-sh-token").on("input", (e) => { state.shToken = e.target.value; });
		$body.find("#jo-sh-back").on("click", () => { state.mode = null; render(); });
		$body.find("#jo-sh-test").on("click", () => runSelfHostTest());
		$body.find("#jo-sh-connect").on("click", saveSelfHost);
		$body.find("#jo-sh-url").focus();
	}

	function renderShResults(result) {
		const checks = result.checks || [];
		const rows = checks.map((c) =>
			`<div class="jo-sh-check">${c.ok ? "✅" : "❌"} <b>${esc(c.check)}</b> — ${esc(c.detail || "")}</div>`
		).join("");
		const overall = result.ok
			? `<div class="jo-sh-ok">All required checks passed.</div>`
			: `<div class="jo-sh-bad">Some checks failed — fix them and retry.</div>`;
		$body.find("#jo-sh-results").html(overall + rows);
	}

	function runSelfHostTest() {
		const url = (state.shUrl || "").trim();
		const tok = (state.shToken || "").trim();
		const $err = $body.find("#jo-sh-err");
		$err.text("");
		if (!url) { $err.text("Enter the openclaw URL first."); return; }
		$body.find("#jo-sh-results").html(`<div class="jo-hint">Testing…</div>`);
		const deep = $body.find("#jo-sh-deep").is(":checked") ? 1 : 0;
		frappe.call({ method: "jarvis.selfhost.test_connection", args: { base_url: url, token: tok, deep } })
			.then((r) => renderShResults(r.message || {}))
			.catch((e) => $err.text(e.message || "Test failed."));
	}

	function saveSelfHost() {
		const url = (state.shUrl || "").trim();
		const tok = (state.shToken || "").trim();
		const $err = $body.find("#jo-sh-err");
		$err.text("");
		if (!url || !tok) { $err.text("openclaw URL and gateway token are both required."); return; }
		setBusy("#jo-sh-connect", true);
		const deep = $body.find("#jo-sh-deep").is(":checked") ? 1 : 0;
		const stream = $body.find("#jo-sh-stream").is(":checked") ? 1 : 0;
		frappe.call({ method: "jarvis.selfhost.save_self_hosted", args: { base_url: url, token: tok, deep, stream } })
			.then((r) => {
				setBusy("#jo-sh-connect", false);
				const m = r.message || {};
				if (m.ok) {
					if (m.warning) frappe.show_alert({ message: __(m.warning), indicator: "orange" }, 15);
					renderSuccess({ agent_url: url }, "ok (self-hosted)");
				} else {
					renderShResults(m.result || {});
					$err.text("Validation failed — fix the checks above, then retry.");
				}
			})
			.catch((e) => { setBusy("#jo-sh-connect", false); $err.text(e.message || "Couldn't connect."); });
	}

	function renderAccount() {
		// Sprint-4 a11y: `<label for=>` pairs each label with its input so
		// screen readers announce the field label when focus lands on the
		// input. `role="alert" aria-live="polite"` on the error container
		// makes the error text announce when populated, instead of being a
		// silent color-only state change. Punch-list "Accessibility:
		// missing <label for=>, missing ARIA roles, color-only error
		// signal" from the 2026-06-16 review.
		$body.html(`
			<h2 class="jo-h">Create your account</h2>
			<p class="jo-sub">We'll set up Jarvis for this site.</p>
			<label class="jo-label" for="jo-email">Work email</label>
			<input class="jo-input" id="jo-email" type="email" placeholder="you@company.com" value="${esc(state.email)}" autocomplete="email" required aria-required="true">
			<label class="jo-label" for="jo-company">Company</label>
			<div id="jo-company-wrap"></div>
			<div class="jo-err" id="jo-acc-err" role="alert" aria-live="polite"></div>
			<div class="jo-actions">
			  <button class="jo-btn jo-btn-primary" id="jo-next">Continue →</button>
			</div>`);
		const companyCtrl = makeCompanyControl();
		const submit = () => {
			state.email = $body.find("#jo-email").val().trim();
			state.company = (companyCtrl ? companyCtrl.get_value() || "" : $body.find("#jo-company").val() || "").trim();
			const ok = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(state.email);
			if (!ok) return $body.find("#jo-acc-err").text("Enter a valid email address.");
			if (!state.company) return $body.find("#jo-acc-err").text("Company name is required.");
			loadPlansThen(() => go(2));
		};
		$body.find("#jo-next").on("click", submit);
		$body.find("#jo-company").on("keydown", (e) => {
			if (e.key !== "Enter") return;
			// When the Link dropdown is open, Enter picks a suggestion.
			const aw = companyCtrl && companyCtrl.awesomplete;
			if (aw && aw.opened) return;
			submit();
		});
		$body.find("#jo-email").focus();
		prefillCompany(companyCtrl);
	}

	// The Company field is a real Frappe Link control over the Company
	// doctype (searchable dropdown, select-only so "Create new" can't yank
	// the customer out of the wizard). Falls back to a plain text input on
	// sites without the doctype so onboarding never blocks on it.
	function makeCompanyControl() {
		const $wrap = $body.find("#jo-company-wrap");
		try {
			const ctrl = frappe.ui.form.make_control({
				parent: $wrap.get(0),
				df: {
					fieldtype: "Link", fieldname: "company", options: "Company",
					placeholder: "Acme Inc.", only_select: 1,
				},
				render_input: true,
			});
			ctrl.$input.attr("id", "jo-company").attr("autocomplete", "organization");
			if (state.company) ctrl.set_value(state.company);
			return ctrl;
		} catch (e) {
			$wrap.replaceWith(`<input class="jo-input" id="jo-company" placeholder="Acme Inc." value="${esc(state.company)}" autocomplete="organization" required aria-required="true">`);
			return null;
		}
	}

	// Auto-fetch the company from the site itself so the customer doesn't
	// retype what ERPNext already knows: user/global default company when
	// set, else auto-fill when the site has exactly one Company. Multiple
	// companies stay a user choice via the Link dropdown. Silent no-op on
	// sites without the Company doctype.
	function prefillCompany(ctrl) {
		const setVal = (v) => {
			if (!v) return;
			const cur = (ctrl ? ctrl.get_value() || "" : $body.find("#jo-company").val() || "").trim();
			if (cur) return;
			state.company = v;
			if (ctrl) ctrl.set_value(v);
			else $body.find("#jo-company").val(v);
		};
		let dflt = null;
		try {
			dflt = frappe.defaults.get_user_default("Company") || frappe.defaults.get_default("company");
		} catch (e) { /* defaults not booted */ }
		if (dflt) return setVal(dflt);
		frappe.db
			.get_list("Company", { fields: ["name"], limit: 2 })
			.then((rows) => {
				if (state.step === 1 && rows && rows.length === 1) setVal(rows[0].name);
			})
			.catch(() => { /* no Company doctype / no read permission */ });
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
			<p class="jo-sub">Pay as you go - no auto-renewal. Extend anytime.</p>
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
			${dev ? `<div class="jo-devnote">Developer mode - payment is skipped (dev signup).</div>` : ""}
			<div class="jo-err" id="jo-pay-err"></div>
			<div class="jo-actions jo-actions-split">
			  <button class="jo-btn jo-btn-ghost" id="jo-back">← Back</button>
			  <button class="jo-btn jo-btn-primary" id="jo-pay">${dev ? "Dev signup &amp; connect" : "Sign up &amp; pay →"}</button>
			</div>`);
		$body.find("#jo-back").on("click", () => go(2));
		// Server-authoritative branch: query is_dev_mode_active at CLICK
		// time, not at page load. The boot-time `dev` value can be stale
		// (operator toggled Jarvis Settings.sandbox_mode after the
		// wizard loaded, or bench cache not cleared post-deploy). If we
		// trusted `dev` here, a stale "false" would charge a customer
		// on a bench that's actually in sandbox - exactly the
		// regression reported 2026-06-13. The heading + button label
		// can be wrong (they're rendered from `dev`) but the actual
		// outcome will be correct.
		$body.find("#jo-pay").on("click", async () => {
			// Visual feedback while the server check is in flight.
			// startPay()/devOnboard() set their own busy state, so we
			// don't need to clear ours - they take over.
			setBusy("#jo-pay", true);
			let isDev = dev;
			try {
				const r = await frappe.call({ method: "jarvis.dev.is_dev_mode_active" });
				isDev = !!(r && r.message && r.message.data && r.message.data.active);
			} catch (_) {
				// Server unreachable - fall back to the boot-time value
				// as a best-effort guess. Better than blocking the user.
				isDev = dev;
			}
			if (isDev) { devOnboard(); } else { startPay(); }
		});
	}

	function renderLlm() {
		const modeTabs = `
			<div class="jo-field">
			  <label class="jo-tabs-label">Setup</label>
			  <div class="jo-tabs jo-tabs-3" role="tablist" data-active="${state.llmMode}">
			    <span class="jo-tabs-thumb" aria-hidden="true"></span>
			    ${["quick","preset","custom"].map(m =>
			      `<button type="button" class="jo-tab ${state.llmMode===m?"jo-tab-active":""}" data-llmmode="${m}" role="tab" aria-selected="${state.llmMode===m}"><span>${m[0].toUpperCase()+m.slice(1)}</span></button>`).join("")}
			  </div>
			</div>`;
		if (state.llmMode === "preset") return renderLlmPreset(modeTabs);
		if (state.llmMode === "custom") return renderLlmCustom(modeTabs);
		return renderLlmQuick(modeTabs);
	}

	function renderLlmQuick(modeTabs) {
		// Defaults arrive lazy: only fill model/baseUrl if the customer hasn't typed.
		const d = PROVIDER_DEFAULTS[state.llmProvider] || { model: "", baseUrl: "" };
		if (!state.llmModel) state.llmModel = d.model;
		if (!state.llmBaseUrl) state.llmBaseUrl = d.baseUrl;
		const providers = Object.keys(PROVIDER_DEFAULTS).map(
			(p) => `<option value="${esc(p)}" ${p === state.llmProvider ? "selected" : ""}>${esc(p)}</option>`
		).join("");
		const iconKey = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>`;
		const iconChat = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;
		const authModeHtml = `
			<div class="jo-field">
			  <label class="jo-tabs-label">Authentication mode</label>
			  <div class="jo-tabs" role="tablist" data-active="${state.authMode}">
			    <span class="jo-tabs-thumb" aria-hidden="true"></span>
			    <button type="button" class="jo-tab ${state.authMode === "api_key" ? "jo-tab-active" : ""}" data-mode="api_key" role="tab" aria-selected="${state.authMode === "api_key"}">${iconKey}<span>API key</span></button>
			    <button type="button" class="jo-tab ${state.authMode === "subscription" ? "jo-tab-active" : ""}" data-mode="subscription" role="tab" aria-selected="${state.authMode === "subscription"}">${iconChat}<span>Chat subscription</span></button>
			  </div>
			</div>`;
		if (state.authMode === "subscription") {
			$body.html(`
				<h2 class="jo-h">Connect your AI</h2>
				<p class="jo-sub">Sign in once with your existing ChatGPT Plus or Gemini Advanced
				   account - no API key, no extra cost. Jarvis will use your subscription quota.</p>
				${modeTabs}
				${authModeHtml}
				${renderSubscriptionPanel()}
				<div class="jo-err" id="jo-llm-err"></div>`);
			wireLlmModeTabs();
			wireAuthModeTabs();
			wireSubscriptionPanel();
			return;
		}
		$body.html(`
			<h2 class="jo-h">Connect your AI</h2>
			<p class="jo-sub">Pick which model Jarvis should use and paste your API key.
			   You can change this anytime in Jarvis Settings.</p>
			${modeTabs}
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
		wireLlmModeTabs();
		wireAuthModeTabs();
	}

	function wireLlmModeTabs() {
		$body.find(".jo-tab[data-llmmode]").on("click", function () {
			const m = $(this).data("llmmode");
			if (m === state.llmMode) return;
			state.llmMode = m;
			if (m !== "quick") cancelSubscriptionFlow();
			renderLlm();
		});
	}

	function renderLlmPreset(modeTabs) {
		if (!presetCatalog.length) {
			$body.html(`
				<h2 class="jo-h">Connect your AI</h2>
				${modeTabs}
				<p class="jo-sub" style="margin-top:16px">Couldn't load presets — use Quick or Custom.</p>`);
			wireLlmModeTabs();
			return;
		}
		const entry = presetCatalog.find(e => e.key === state.selectedPreset) || null;
		const missing = entry ? jarvis_onboarding_llm.missingVendorKeys(entry, state.presetKeys) : [];
		const saveBtnDisabled = (!entry || missing.length > 0) ? "disabled" : "";

		const cardGroup = (kind) => presetCatalog
			.filter(e => e.kind === kind)
			.map(e => {
				const sel = state.selectedPreset === e.key ? "selected" : "";
				const ladder = (e.models || []).slice().sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
					.map((m, i) => `<div class="jo-preset-model"><span class="jo-hint">${i === 0 ? "Runs every turn" : "Backup " + i}</span> <b>${esc(m.model)}</b></div>`)
					.join("");
				return `<div class="jo-preset-card ${sel}" data-pkey="${esc(e.key)}">
					<div class="jo-preset-label">${esc(e.label)}</div>
					<div class="jo-hint" style="margin-bottom:8px">${esc(e.blurb || "")}</div>
					${ladder}
				</div>`;
			}).join("");

		const singleVendorCards = cardGroup("single_vendor");
		const crossVendorCards = cardGroup("cross_vendor");

		let keyFieldsHtml = "";
		if (entry) {
			const vendors = jarvis_onboarding_llm.uniqueVendors(entry);
			keyFieldsHtml = vendors.map(v => `
				<div class="jo-field">
				  <label>${esc(v)} API key</label>
				  <input type="password" class="jo-input jo-preset-key" data-vendor="${esc(v)}" value="${esc(state.presetKeys[v] || "")}" placeholder="sk-..." autocomplete="off"/>
				</div>`).join("");
		}

		$body.html(`
			<h2 class="jo-h">Connect your AI</h2>
			<p class="jo-sub">Pick a preset failover ladder. Keys are stored encrypted.</p>
			${modeTabs}
			<div style="max-height:min(48vh,440px);overflow-y:auto;padding-right:4px;scrollbar-gutter:stable">
				${singleVendorCards ? `<p class="jo-tabs-label" style="margin-top:16px">Single-vendor ladders</p><div class="jo-preset-cards">${singleVendorCards}</div>` : ""}
				${crossVendorCards ? `<p class="jo-tabs-label" style="margin-top:14px">Cross-vendor presets</p><div class="jo-preset-cards">${crossVendorCards}</div>` : ""}
			</div>
			${entry ? `<div style="margin-top:18px">${keyFieldsHtml}</div>` : ""}
			<div class="jo-err" id="jo-llm-err"></div>
			<div class="jo-actions jo-actions-split">
			  <button class="jo-btn jo-btn-ghost" id="jo-llm-skip">Skip for now</button>
			  <button class="jo-btn jo-btn-primary" id="jo-preset-save" ${saveBtnDisabled}>Save &amp; finish →</button>
			</div>`);

		$body.find(".jo-preset-card").on("click", function () {
			state.selectedPreset = $(this).data("pkey");
			// Reset keys when switching presets
			state.presetKeys = {};
			renderLlm();
		});
		$body.find(".jo-preset-key").on("input", function () {
			const vendor = $(this).data("vendor");
			state.presetKeys[vendor] = $(this).val();
			// Update save button live
			const e2 = presetCatalog.find(e => e.key === state.selectedPreset);
			const m2 = e2 ? jarvis_onboarding_llm.missingVendorKeys(e2, state.presetKeys) : ["?"];
			$body.find("#jo-preset-save").prop("disabled", m2.length > 0);
		});
		$body.find("#jo-llm-skip").on("click", () => renderSuccess(state.successData || {}));
		$body.find("#jo-preset-save").on("click", savePreset);
		wireLlmModeTabs();
	}

	// Transient per-row state for the inline paste-back connect flow (chat
	// subscription rows). Never emitted on save. Mirrors jarvis_account.js.
	function blankConnect() {
		return { open: false, loading: false, error: "", nonce: "", authorizeUrl: "", pastedUrl: "" };
	}

	// A fresh custom row. API-key by default; carries subscription scaffolding
	// (rotation/upstream/accounts/connect) so the credType toggle can flip
	// without re-seeding. Matches jarvis_account.js blankCustomRow.
	function blankCustomRow() {
		const firstProvider = Object.keys(PROVIDER_DEFAULTS)[0] || "Anthropic";
		return {
			credType: "api_key", provider: firstProvider, model: "",
			apiKey: "", baseUrl: "",
			rotation: "sticky", upstream: "openai", accounts: [], connect: blankConnect(),
		};
	}

	function renderLlmCustom(modeTabs) {
		const rows = state.customRows;
		// Mode badge counts VALID rows: subscription rows count once they have a
		// model id; API-key rows need a provider + model. Mirrors the account
		// page's renderModeBadge so the Direct/Proxy pill matches everywhere.
		const valid = rows.filter((r) => r && (
			r.credType === "subscription"
				? (r.model || "").trim()
				: ((r.provider || "").trim() && (r.model || "").trim())
		));
		const mode = jarvis_onboarding_llm.deriveMode(valid, null);
		const modeBadge = `<span class="jo-hint" style="margin-left:8px">${mode === "proxy" ? "🔀 Proxy (failover)" : "⟶ Direct"}</span>`;

		const rowsHtml = rows.map((r, i) => renderCustomRow(r, i, rows.length)).join("");

		$body.html(`
			<h2 class="jo-h">Connect your AI${modeBadge}</h2>
			<p class="jo-sub">Build your own failover list. First model runs every turn; others are backups. Each row is an <b>API key</b> or a <b>Chat subscription</b> (multiple pooled accounts).</p>
			${modeTabs}
			<div id="jo-custom-rows" style="margin-top:16px">${rowsHtml || `<div class="jo-empty" style="padding:8px 0">No models yet — add one below.</div>`}</div>
			<div class="jo-actions" style="justify-content:flex-start;margin-top:8px">
			  <button class="jo-btn jo-btn-ghost jo-btn-small" id="jo-custom-add">+ Add model</button>
			</div>
			<div class="jo-err" id="jo-llm-err"></div>
			<div class="jo-actions jo-actions-split">
			  <button class="jo-btn jo-btn-ghost" id="jo-llm-skip">Skip for now</button>
			  <button class="jo-btn jo-btn-primary" id="jo-custom-save">Save &amp; finish →</button>
			</div>`);

		wireLlmModeTabs();

		// Credential-type toggle (API key ⇄ Chat subscription).
		$body.find(".jo-cred-btn").on("click", function () {
			const i = +$(this).data("i");
			const cred = $(this).data("cred");
			const row = state.customRows[i];
			if (!row || row.credType === cred) return;
			row.credType = cred;
			if (cred === "subscription") {
				if (!row.rotation) row.rotation = "sticky";
				if (!row.upstream) row.upstream = "openai";
				if (!Array.isArray(row.accounts)) row.accounts = [];
				row.connect = blankConnect();
			}
			renderLlm();
		});
		// Reorder / remove rows.
		$body.find(".jo-row-up").on("click", function () {
			const i = +$(this).data("i");
			if (i > 0) { state.customRows = jarvis_onboarding_llm.reorder(state.customRows, i, i - 1); renderLlm(); }
		});
		$body.find(".jo-row-down").on("click", function () {
			const i = +$(this).data("i");
			if (i < state.customRows.length - 1) { state.customRows = jarvis_onboarding_llm.reorder(state.customRows, i, i + 1); renderLlm(); }
		});
		$body.find(".jo-row-rm").on("click", function () {
			const i = +$(this).data("i");
			state.customRows = state.customRows.filter((_, idx) => idx !== i);
			renderLlm();
		});
		// API-key row fields. Provider change re-renders (autofill defaults +
		// mode badge); text inputs update state in place to preserve focus.
		$body.find(".jo-custom-prov").on("change", function () {
			const i = +$(this).data("i");
			const p = $(this).val();
			const d = PROVIDER_DEFAULTS[p] || { model: "", baseUrl: "" };
			const row = state.customRows[i] || {};
			const patch = { provider: p };
			if (!(row.model || "").trim() && d.model) patch.model = d.model;
			if (!(row.baseUrl || "").trim() && d.baseUrl) patch.baseUrl = d.baseUrl;
			state.customRows[i] = Object.assign({}, row, patch);
			renderLlm();
		});
		$body.find(".jo-custom-model").on("input", function () {
			const i = +$(this).data("i");
			if (state.customRows[i]) state.customRows[i].model = $(this).val();
		});
		$body.find(".jo-custom-key").on("input", function () {
			const i = +$(this).data("i");
			if (state.customRows[i]) state.customRows[i].apiKey = $(this).val();
		});
		$body.find(".jo-custom-base").on("input", function () {
			const i = +$(this).data("i");
			if (state.customRows[i]) state.customRows[i].baseUrl = $(this).val();
		});
		// Subscription row fields. Upstream change re-renders so the model
		// datalist suggestions follow the chosen upstream (openai/google).
		$body.find(".jo-custom-upstream").on("change", function () {
			const i = +$(this).data("i");
			if (state.customRows[i]) state.customRows[i].upstream = $(this).val();
			renderLlm();
		});
		$body.find(".jo-custom-rotation").on("change", function () {
			const i = +$(this).data("i");
			if (state.customRows[i]) state.customRows[i].rotation = $(this).val();
		});
		$body.find(".jo-row-acct-rm").on("click", function () {
			const i = +$(this).data("i");
			const ai = +$(this).data("ai");
			const row = state.customRows[i];
			if (row) { row.accounts = (row.accounts || []).filter((_, j) => j !== ai); renderLlm(); }
		});
		// Per-account connect flow (begin/complete_pool_account_signin).
		$body.find(".jo-conn-start").on("click", function () { startPoolConnect(+$(this).data("i")); });
		$body.find(".jo-conn-open").on("click", function () {
			const i = +$(this).data("i");
			const url = (state.customRows[i].connect || {}).authorizeUrl;
			if (url) window.open(url, "_blank", "noopener,noreferrer");
		});
		// Copy the authorize URL — same helper + "Copied ✓" feedback as the
		// Quick-mode subscription copy button (#jo-sub-copy-url).
		$body.find(".jo-conn-copy").on("click", function () {
			const i = +$(this).data("i");
			const url = (state.customRows[i].connect || {}).authorizeUrl;
			if (!url) return;
			const $btn = $(this);
			copyTextWithFallback(url).then(() => {
				const orig = $btn.text();
				$btn.text("Copied ✓");
				setTimeout(() => $btn.text(orig), 1400);
				frappe.show_alert({ indicator: "green", message: __("Sign-in URL copied") });
			}).catch(() => {
				frappe.show_alert({ indicator: "red", message: __("Could not copy - select the URL above and copy manually") });
			});
		});
		$body.find(".jo-conn-url").on("input", function () {
			const i = +$(this).data("i");
			if (state.customRows[i].connect) state.customRows[i].connect.pastedUrl = $(this).val();
		});
		$body.find(".jo-conn-cancel").on("click", function () {
			const i = +$(this).data("i");
			if (state.customRows[i]) state.customRows[i].connect = blankConnect();
			renderLlm();
		});
		$body.find(".jo-conn-finish").on("click", function () { finishPoolConnect(+$(this).data("i")); });
		// Add row / skip / save.
		$body.find("#jo-custom-add").on("click", () => {
			state.customRows = state.customRows.concat(blankCustomRow());
			renderLlm();
		});
		$body.find("#jo-llm-skip").on("click", () => renderSuccess(state.successData || {}));
		$body.find("#jo-custom-save").on("click", saveCustom);
	}

	function renderCustomRow(r, i, n) {
		const credType = r.credType || "api_key";
		const head = `
			<div class="jo-crow-head">
				<div class="jo-cred-toggle">
					${["api_key", "subscription"].map((t) =>
						`<button type="button" class="jo-cred-btn ${credType === t ? "jo-cred-active" : ""}" data-i="${i}" data-cred="${t}">${t === "api_key" ? "API key" : "Chat subscription"}</button>`
					).join("")}
				</div>
				<div class="jo-crow-move">
					<button type="button" class="jo-btn jo-btn-ghost jo-btn-small jo-row-up" data-i="${i}" title="Move up" ${i === 0 ? "disabled" : ""}>↑</button>
					<button type="button" class="jo-btn jo-btn-ghost jo-btn-small jo-row-down" data-i="${i}" title="Move down" ${i === n - 1 ? "disabled" : ""}>↓</button>
					<button type="button" class="jo-btn jo-btn-ghost jo-btn-small jo-row-rm" data-i="${i}" title="Remove">✕</button>
				</div>
			</div>`;
		let bodyHtml;
		if (credType === "subscription") {
			bodyHtml = renderCustomSubBody(r, i);
		} else {
			const provOpts = Object.keys(PROVIDER_DEFAULTS)
				.map((p) => `<option value="${esc(p)}" ${p === providerLabel(r.provider || "") ? "selected" : ""}>${esc(p)}</option>`).join("");
			const dlId = `jo-dl-model-${i}`;
			bodyHtml = `
				<div class="jo-crow-grid">
					<select class="jo-input jo-custom-prov" data-i="${i}">${provOpts}</select>
					<input type="text" list="${dlId}" class="jo-input jo-custom-model" data-i="${i}" value="${esc(r.model || "")}" placeholder="model id"/>
					<input type="password" class="jo-input jo-custom-key" data-i="${i}" value="${esc(r.apiKey || "")}" placeholder="API key" autocomplete="off"/>
					<input type="text" class="jo-input jo-custom-base" data-i="${i}" value="${esc(r.baseUrl || "")}" placeholder="base URL (optional)"/>
				</div>
				${renderModelDatalist(dlId, modelSuggestionsForProvider(r.provider || ""))}`;
		}
		const runsLabel = i === 0 ? "Runs every turn" : "Backup " + i;
		return `<div class="jo-crow" data-i="${i}"><div class="jo-crow-tag">${runsLabel}</div>${head}${bodyHtml}</div>`;
	}

	function renderCustomSubBody(r, i) {
		const rotation = r.rotation || "sticky";
		const upstream = r.upstream || "openai";
		const rotOpts = [["sticky", "Sticky"], ["round_robin", "Round robin"], ["least_used", "Least used"]]
			.map(([v, l]) => `<option value="${v}" ${rotation === v ? "selected" : ""}>${l}</option>`).join("");
		const upOpts = [["openai", "OpenAI"], ["google", "Google"]]
			.map(([v, l]) => `<option value="${v}" ${upstream === v ? "selected" : ""}>${l}</option>`).join("");
		const accounts = r.accounts || [];
		const accountsHtml = accounts.length
			? accounts.map((a, ai) => `<div class="jo-acct">
					<span class="jo-acct-dot">connected</span>
					<span class="jo-acct-label">${esc(a.label || a.account_ref)}</span>
					<span class="jo-hint-inline">${esc(a.upstream || "")}</span>
					<button type="button" class="jo-acct-rm jo-row-acct-rm" data-i="${i}" data-ai="${ai}" title="Remove account">✕</button>
				</div>`).join("")
			: `<div class="jo-hint-inline" style="display:block;margin:4px 0 8px">No accounts connected yet.</div>`;

		const c = r.connect || {};
		let connectHtml = "";
		if (c.open) {
			if (c.authorizeUrl) {
				connectHtml = `
					<div class="jo-connect">
						<p class="jo-hint-inline" style="display:block;margin-bottom:8px">Open the sign-in URL, authorize, then paste the redirected URL (it starts with <code>http://localhost:1455/…</code>).</p>
						<div class="jo-url-row" style="margin-bottom:8px">
							<code class="jo-url-text" title="${esc(c.authorizeUrl)}">${esc(c.authorizeUrl)}</code>
							<button type="button" class="jo-btn jo-btn-ghost jo-btn-small jo-conn-copy" data-i="${i}" title="Copy URL">Copy</button>
							<button type="button" class="jo-btn jo-btn-ghost jo-btn-small jo-conn-open" data-i="${i}">Open ↗</button>
						</div>
						<textarea class="jo-input jo-conn-url" data-i="${i}" rows="2" placeholder="Paste the URL after you sign in">${esc(c.pastedUrl || "")}</textarea>
						<div class="jo-actions" style="margin-top:8px;justify-content:flex-start;gap:8px">
							<button type="button" class="jo-btn jo-btn-ghost jo-conn-cancel" data-i="${i}">Cancel</button>
							<button type="button" class="jo-btn jo-btn-primary jo-conn-finish" data-i="${i}" ${c.loading ? "disabled" : ""}>${c.loading ? "Connecting…" : "Connect"}</button>
						</div>
						${c.error ? `<div class="jo-err">${esc(c.error)}</div>` : ""}
					</div>`;
			} else {
				connectHtml = `<div class="jo-connect"><div class="jo-hint-inline">${c.error ? "" : "Starting sign-in…"}</div>${c.error ? `<div class="jo-err">${esc(c.error)}</div>` : ""}</div>`;
			}
		}
		const dlId = `jo-dl-submodel-${i}`;
		return `
			<div class="jo-crow-grid jo-crow-grid-sub">
				<input type="text" list="${dlId}" class="jo-input jo-custom-model" data-i="${i}" value="${esc(r.model || "")}" placeholder="model id (e.g. gpt-5.5)"/>
				<select class="jo-input jo-custom-upstream" data-i="${i}" title="Upstream">${upOpts}</select>
				<select class="jo-input jo-custom-rotation" data-i="${i}" title="Account rotation">${rotOpts}</select>
			</div>
			${renderModelDatalist(dlId, subModelSuggestions(upstream))}
			<div class="jo-accts">${accountsHtml}</div>
			${connectHtml}
			<button type="button" class="jo-btn jo-btn-ghost jo-btn-small jo-conn-start" data-i="${i}">+ Connect account</button>`;
	}

	// Start the inline paste-back sign-in for a subscription row: mint an
	// authorize_url (begin_pool_account_signin) and reveal the Open/paste UI.
	// Guards model-required-before-connect. Mirrors jarvis_account.js.
	function startPoolConnect(i) {
		const row = state.customRows[i];
		if (!row) return;
		if (!(row.model || "").trim()) {
			row.connect = Object.assign(blankConnect(), { open: true, error: "Enter a model id before connecting an account." });
			renderLlm();
			return;
		}
		row.connect = Object.assign(blankConnect(), { open: true, loading: true });
		renderLlm();
		const provider = row.upstream === "google" ? "Google" : "OpenAI";
		frappe.call({
			method: "jarvis.oauth.api.begin_pool_account_signin",
			args: { provider, model: row.model.trim() },
		}).then((r) => {
			const m = r.message || {};
			const cur = state.customRows[i];
			if (!cur) return;
			if (!m.ok) {
				cur.connect = Object.assign(blankConnect(), { open: true, error: (m.error && m.error.message) || "Couldn't start sign-in." });
			} else {
				cur.connect = Object.assign(blankConnect(), { open: true, loading: false, nonce: m.data.nonce, authorizeUrl: m.data.authorize_url });
			}
			renderLlm();
		}).catch((e) => {
			const cur = state.customRows[i];
			if (!cur) return;
			cur.connect = Object.assign(blankConnect(), { open: true, error: e.message || "Couldn't reach Jarvis." });
			renderLlm();
		});
	}

	// Complete the paste-back sign-in: exchange the redirected URL for an
	// account (complete_pool_account_signin, capture-only) and push it into the
	// row's accounts. Mirrors jarvis_account.js.
	function finishPoolConnect(i) {
		const row = state.customRows[i];
		if (!row || !row.connect || !row.connect.nonce) return;
		const pasted = (row.connect.pastedUrl || "").trim();
		if (!pasted) {
			row.connect.error = "Paste the URL you were redirected to.";
			renderLlm();
			return;
		}
		row.connect.loading = true;
		row.connect.error = "";
		renderLlm();
		frappe.call({
			method: "jarvis.oauth.api.complete_pool_account_signin",
			args: { nonce: row.connect.nonce, redirected_url: pasted },
		}).then((r) => {
			const m = r.message || {};
			const cur = state.customRows[i];
			if (!cur) return;
			if (!m.ok) {
				cur.connect.loading = false;
				const code = (m.error && m.error.code) ? m.error.code + ": " : "";
				cur.connect.error = code + ((m.error && m.error.message) || "Sign-in failed.");
				renderLlm();
				return;
			}
			const d = m.data || {};
			if (!Array.isArray(cur.accounts)) cur.accounts = [];
			cur.accounts.push({
				upstream: cur.upstream || "openai",
				account_ref: d.account_ref,
				label: d.label || d.account_email || d.account_ref,
				oauth_blob: d.oauth_blob || "",
			});
			cur.connect = blankConnect();
			frappe.show_alert({ message: __("Account connected."), indicator: "green" });
			renderLlm();
		}).catch((e) => {
			const cur = state.customRows[i];
			if (!cur) return;
			cur.connect.loading = false;
			cur.connect.error = e.message || "Couldn't reach Jarvis.";
			renderLlm();
		});
	}

	// Emit the per-row backend shape save_llm_pool expects: API-key rows carry
	// {provider, model, api_key, base_url, order}; subscription rows carry
	// {model, order, subscription:{rotation, accounts:[{upstream, account_ref,
	// label, oauth_blob}]}}. Matches jarvis_account.js buildCustomSaveModels.
	function buildCustomSaveModels() {
		return (state.customRows || []).map((r, i) => {
			if (r.credType === "subscription") {
				return {
					model: (r.model || "").trim(),
					order: i,
					subscription: {
						rotation: r.rotation || "sticky",
						accounts: (r.accounts || []).map((a) => ({
							upstream: a.upstream || "openai",
							account_ref: a.account_ref,
							label: a.label,
							oauth_blob: a.oauth_blob || "",
						})),
					},
				};
			}
			const m = { provider: (r.provider || "").trim(), model: (r.model || "").trim(), api_key: (r.apiKey || "").trim(), order: i };
			const b = (r.baseUrl || "").trim();
			if (b) m.base_url = b;
			return m;
		});
	}

	function saveCustom() {
		const models = buildCustomSaveModels();
		const check = jarvis_onboarding_llm.validatePool(models, null);
		if (!check.ok) { $body.find("#jo-llm-err").text(check.error); return; }
		setBusy("#jo-custom-save", true);
		frappe.call({ method: "jarvis.onboarding.save_llm_pool",
			args: { models: JSON.stringify(models), preset: null, routing_mode: "failover" } })
			.then((r) => {
				const m = r.message || {}; const status = (m.last_sync_status || "").trim();
				if (status.startsWith("pending:")) pollSyncStatus(status);
				else { setBusy("#jo-custom-save", false); renderSuccess(state.successData || {}, status); }
			})
			.catch((e) => { setBusy("#jo-custom-save", false); $body.find("#jo-llm-err").text(e.message || "Couldn't save models."); });
	}

	function savePreset() {
		const entry = presetCatalog.find(e => e.key === state.selectedPreset);
		if (!entry || jarvis_onboarding_llm.missingVendorKeys(entry, state.presetKeys).length) {
			$body.find("#jo-llm-err").text("Presets need every vendor's key. Use Quick or Custom to finish with fewer keys.");
			return;
		}
		const models = jarvis_onboarding_llm.presetToModels(entry, state.presetKeys);
		setBusy("#jo-preset-save", true);
		frappe.call({ method: "jarvis.onboarding.save_llm_pool",
			args: { models: JSON.stringify(models), preset: entry.key, routing_mode: "failover" } })
			.then((r) => {
				const m = r.message || {}; const status = (m.last_sync_status || "").trim();
				if (status.startsWith("pending:")) pollSyncStatus(status);
				else { setBusy("#jo-preset-save", false); renderSuccess(state.successData || {}, status); }
			})
			.catch((e) => { setBusy("#jo-preset-save", false); $body.find("#jo-llm-err").text(e.message || "Couldn't save preset."); });
	}

	function wireAuthModeTabs() {
		$body.find(".jo-tab[data-mode]").on("click", function () {
			const mode = $(this).data("mode");
			if (mode === state.authMode) return;
			state.authMode = mode;
			// Reset subscription state when switching back to api_key
			if (state.authMode === "api_key") cancelSubscriptionFlow();
			renderLlm();
		});
	}

	function renderSubscriptionPanel() {
		// Screen 2 - authorize URL shown, awaiting paste-back
		if (state.subAuthorizeUrl) {
			// Sprint-4 punch-list "Subscription paste-back instructions
			// confusing/brittle":
			//   - Live URL-shape validation (the `code=` check below +
			//     wireSubscriptionPanel's input handler) gives instant
			//     feedback instead of waiting for Submit -> server-side
			//     `missing_code` round trip.
			//   - `minsLeft` re-rendered every 30s via setInterval so the
			//     customer sees the countdown tick down, not a frozen
			//     "X minutes" stamp from page-render time.
			//   - "Start over" is clearer than "Cancel" (the user might
			//     have already clicked Authorize; cancelling sounds like
			//     it undoes the sign-in).
			//   - Expandable "Why an error page?" explains the
			//     localhost:1455 trick so the customer doesn't think
			//     something broke.
			const minsLeft = Math.max(0, Math.floor((state.subExpiresAt - Date.now()) / 60000));
			return `
				<p class="jo-hint" style="margin-bottom:14px"><strong>Step 1</strong> - Sign in with your ${esc(state.subProvider)} account in a new tab.</p>
				<div class="jo-actions" style="margin-bottom:10px">
				  <button class="jo-btn jo-btn-primary" id="jo-sub-open-url">Open Sign-in URL →</button>
				</div>
				<div class="jo-url-row" style="margin-bottom:18px">
				  <code class="jo-url-text" id="jo-sub-url-text" title="${esc(state.subAuthorizeUrl)}">${esc(state.subAuthorizeUrl)}</code>
				  <button type="button" class="jo-btn jo-btn-ghost jo-btn-small" id="jo-sub-copy-url" title="Copy URL">Copy</button>
				</div>
				<p class="jo-hint"><strong>Step 2</strong> - After clicking Authorize, your browser will show a page saying <em>"This site can't be reached."</em> <strong>That's expected.</strong> Copy the URL from your browser's address bar (it'll start with <code>http://localhost:1455/auth/callback?code=…</code>) and paste it here:</p>
				<div class="jo-field">
				  <label class="jo-label" for="jo-sub-pasted-url">Pasted URL</label>
				  <textarea class="jo-input" id="jo-sub-pasted-url" rows="3" placeholder="http://localhost:1455/auth/callback?code=..." aria-describedby="jo-sub-paste-hint"></textarea>
				  <div class="jo-hint" id="jo-sub-paste-hint" style="font-size:12px;margin-top:6px;color:var(--text-muted)"></div>
				</div>
				<details class="jo-help" style="margin:0 0 12px">
				  <summary style="cursor:pointer;font-size:13px">Why does my browser show a "site can't be reached" error?</summary>
				  <p class="jo-sub" style="margin-top:6px;font-size:13px">After you click Authorize, ${esc(state.subProvider)} redirects your browser back to <code>localhost:1455</code> - that's a port on your machine. Nothing is listening on it (Jarvis runs on this site, not on your laptop), so your browser shows an error. The redirect itself succeeded though, and the URL in your address bar carries the one-time code we need. Just copy that whole URL and paste it above.</p>
				</details>
				<div class="jo-actions jo-actions-split">
				  <button class="jo-btn jo-btn-ghost" id="jo-sub-cancel">Start over</button>
				  <button class="jo-btn jo-btn-primary" id="jo-sub-submit" disabled>Submit →</button>
				</div>
				<div class="jo-hint" id="jo-sub-countdown" style="margin-top:14px;font-size:12px" aria-live="polite">Link valid for ~${minsLeft} minute${minsLeft === 1 ? "" : "s"}.</div>`;
		}
		// Screen 1 - provider + model picker (not yet started)
		const provOptions = Object.keys(subscriptionModels).map(
			(p) => `<option value="${esc(p)}" ${p === state.subProvider ? "selected" : ""}>${esc(p)}</option>`
		).join("");
		const modelOptions = (subscriptionModels[state.subProvider] || []).map(
			(m) => `<option value="${esc(m)}" ${m === state.subModel ? "selected" : ""}>${esc(m)}</option>`
		).join("");
		return `
			<div class="jo-field">
			  <label>Provider</label>
			  <select id="jo-sub-provider" class="jo-input">${provOptions}</select>
			</div>
			<div class="jo-field">
			  <label>Default model</label>
			  <select id="jo-sub-model" class="jo-input">${modelOptions}</select>
			</div>
			<div class="jo-actions">
			  <button class="jo-btn jo-btn-primary" id="jo-sub-signin">Sign in with ${esc(state.subProvider)} →</button>
			</div>`;
	}

	function wireSubscriptionPanel() {
		// Screen 1 wiring
		$body.find("#jo-sub-provider").on("change", (e) => {
			state.subProvider = e.target.value;
			state.subModel = (subscriptionModels[state.subProvider] || [])[0] || "";
			renderLlm();
		});
		$body.find("#jo-sub-model").on("change", (e) => {
			state.subModel = e.target.value;
		});
		$body.find("#jo-sub-signin").on("click", startSubscriptionSignin);
		// Screen 2 wiring
		$body.find("#jo-sub-open-url").on("click", () => {
			if (state.subAuthorizeUrl) {
				window.open(state.subAuthorizeUrl, "_blank", "noopener,noreferrer");
			}
		});
		$body.find("#jo-sub-copy-url").on("click", function () {
			if (!state.subAuthorizeUrl) return;
			const $btn = $(this);
			copyTextWithFallback(state.subAuthorizeUrl).then(() => {
				const orig = $btn.text();
				$btn.text("Copied ✓");
				setTimeout(() => $btn.text(orig), 1400);
				frappe.show_alert({ indicator: "green", message: __("Sign-in URL copied") });
			}).catch(() => {
				frappe.show_alert({ indicator: "red", message: __("Could not copy - select the URL above and copy manually") });
			});
		});
		$body.find("#jo-sub-cancel").on("click", () => {
			stopSubCountdown();
			cancelSubscriptionFlow();
			renderLlm();
		});
		$body.find("#jo-sub-submit").on("click", submitPastedUrl);

		// Live URL-shape validation for the paste-back textarea.
		// Acceptance criteria (deliberately permissive - we let the bench
		// run the strict parse): contains "code=" somewhere AND parses as a
		// URL OR starts with "?" / "code=". The inline hint shows what's
		// missing so the customer can tell whether they pasted the wrong
		// thing before the round-trip.
		const $ta = $body.find("#jo-sub-pasted-url");
		const $hint = $body.find("#jo-sub-paste-hint");
		const $submit = $body.find("#jo-sub-submit");
		const validateInline = () => {
			const raw = ($ta.val() || "").trim();
			if (!raw) {
				$hint.text("").css("color", "");
				$submit.prop("disabled", true);
				return;
			}
			if (!/code=[^&\s]+/i.test(raw)) {
				$hint.text("This URL is missing a `code=` parameter. Paste the full URL from your browser's address bar.").css("color", "var(--red-600, #b91c1c)");
				$submit.prop("disabled", true);
				return;
			}
			// Acceptable shapes: full URL, ?-prefixed query, or bare
			// query. The bench's _parse_redirected_url handles all three.
			const looksOk = /^(https?:\/\/|\?|code=)/i.test(raw);
			if (!looksOk) {
				$hint.text("Doesn't look like a callback URL. Paste the FULL address starting with http://localhost:1455/...").css("color", "var(--red-600, #b91c1c)");
				$submit.prop("disabled", true);
				return;
			}
			$hint.text("Looks good. Click Submit to finish sign-in.").css("color", "var(--green-700, #15803d)");
			$submit.prop("disabled", false);
		};
		$ta.on("input paste", () => setTimeout(validateInline, 0));

		// Countdown refresh: rewrite the "Link valid for ~N minutes" hint
		// every 30s while this screen is mounted so the customer sees the
		// timer move. cleared on cancel + on screen-leave by render().
		startSubCountdown();
	}

	// Module-level so cancelSubscriptionFlow / wireSubscriptionPanel can
	// share a single timer handle without leaking duplicates on re-render.
	let _subCountdownTimer = null;
	function startSubCountdown() {
		stopSubCountdown();
		const tick = () => {
			if (!state.subExpiresAt) {
				stopSubCountdown();
				return;
			}
			const $c = $body.find("#jo-sub-countdown");
			if ($c.length === 0) {
				// User navigated away (panel re-rendered into a different
				// screen). Clear and bail.
				stopSubCountdown();
				return;
			}
			const minsLeft = Math.max(0, Math.floor((state.subExpiresAt - Date.now()) / 60000));
			if (minsLeft <= 0) {
				$c.text("Link expired. Click Start over to generate a fresh sign-in URL.").css("color", "var(--red-600, #b91c1c)");
				stopSubCountdown();
				return;
			}
			$c.text(`Link valid for ~${minsLeft} minute${minsLeft === 1 ? "" : "s"}.`);
		};
		tick();
		_subCountdownTimer = setInterval(tick, 30 * 1000);
	}
	function stopSubCountdown() {
		if (_subCountdownTimer) {
			clearInterval(_subCountdownTimer);
			_subCountdownTimer = null;
		}
	}

	function startSubscriptionSignin() {
		const $err = $body.find("#jo-llm-err");
		$err.text("");
		setBusy("#jo-sub-signin", true);
		frappe.call({
			method: "jarvis.oauth.api.begin_paste_signin",
			args: { provider: state.subProvider, model: state.subModel },
		}).then((r) => {
			setBusy("#jo-sub-signin", false);
			const m = r.message || {};
			if (!m.ok) {
				$err.text((m.error && m.error.message) || "Couldn't start sign-in. Please try again.");
				return;
			}
			state.subNonce = m.data.nonce;
			state.subAuthorizeUrl = m.data.authorize_url;
			state.subExpiresAt = Date.now() + m.data.expires_in * 1000;
			renderLlm();
		}).catch((e) => {
			setBusy("#jo-sub-signin", false);
			$err.text(e.message || "Couldn't reach Jarvis. Try again in a moment.");
		});
	}

	function submitPastedUrl() {
		const $err = $body.find("#jo-llm-err");
		$err.text("");
		const pasted = ($body.find("#jo-sub-pasted-url").val() || "").trim();
		if (!pasted) {
			$err.text("Paste the URL from your browser's address bar first.");
			return;
		}
		// Once we're round-tripping to the bench, the screen's about to
		// flip either way (success -> save flow, failure -> back to
		// signin form). Stop the countdown ticker now to free the timer
		// even on the success path.
		stopSubCountdown();
		setBusy("#jo-sub-submit", true);
		frappe.call({
			method: "jarvis.oauth.api.complete_paste_signin",
			args: { nonce: state.subNonce, redirected_url: pasted },
		}).then((r) => {
			setBusy("#jo-sub-submit", false);
			const m = r.message || {};
			if (!m.ok) {
				const errCode = (m.error && m.error.code) || "";
				const errMsg = (m.error && m.error.message) || "Sign-in failed.";
				$err.text(`${errCode}: ${errMsg}`);
				if (errCode === "expired" || errCode === "unknown_nonce") {
					setTimeout(() => { cancelSubscriptionFlow(); renderLlm(); }, 2500);
				}
				return;
			}
			const connectedEmail = (m.data && m.data.account_email) || "";
			cancelSubscriptionFlow();
			renderSuccess(state.successData || {}, "ok (subscription)", { connectedEmail });
		}).catch((e) => {
			setBusy("#jo-sub-submit", false);
			$err.text(e.message || "Couldn't reach Jarvis.");
		});
	}

	function cancelSubscriptionFlow() {
		stopSubCountdown();
		state.subNonce = null;
		state.subAuthorizeUrl = null;
		state.subExpiresAt = null;
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
			const m = r.message || {};
			const status = (m.last_sync_status || "").trim();
			// 2026-06-09: on_update is now async - the save call returns
			// immediately with "pending: ..." while the admin restart
			// runs in the background. Poll for the final status.
			if (status.startsWith("pending:")) {
				pollSyncStatus(status);
			} else {
				setBusy("#jo-llm-save", false);
				renderSuccess(state.successData || {}, status);
			}
		}).catch((e) => {
			setBusy("#jo-llm-save", false);
			$err.text(e.message || "Couldn't save LLM settings. Please try again.");
		});
	}

	function pollSyncStatus(initialStatus) {
		// Render an in-place "provisioning" panel before polling. Keep the
		// save button busy throughout so the user can't double-submit.
		renderProvisioning(initialStatus);
		const startedAt = Date.now();
		// Admin's healthz timeout is 60s; bench round-trip + buffer ≈ 90s.
		// Cap at 150s so we surface a graceful "still working" state even
		// if the container is unusually slow to come back up.
		const TIMEOUT_MS = 150 * 1000;
		const tick = () => {
			frappe.call({ method: "jarvis.onboarding.get_llm_sync_status" })
				.then((r) => {
					const m = r.message || {};
					const status = (m.last_sync_status || "").trim();
					if (!m.pending) {
						setBusy("#jo-llm-save", false);
						renderSuccess(state.successData || {}, status);
						return;
					}
					if (Date.now() - startedAt > TIMEOUT_MS) {
						// Sprint-4 punch-list "Provisioning poll silently
						// times out into success screen": the previous
						// shape called renderSuccess with the still-
						// pending status, showing a green ring + "You're
						// connected!" even though the agent wasn't ready.
						// Customers landed on chat thinking it was set up
						// and hit a wall. Now: render the in-between
						// "Almost there" state with a yellow ring, the
						// real status, and a Check status button.
						setBusy("#jo-llm-save", false);
						renderAlmostThere(state.successData || {}, status || "pending: container still provisioning");
						return;
					}
					setTimeout(tick, 2500);
				})
				.catch(() => {
					// Polling failure is transient - keep trying until timeout.
					if (Date.now() - startedAt > TIMEOUT_MS) {
						setBusy("#jo-llm-save", false);
						renderAlmostThere(state.successData || {}, "pending: lost contact while provisioning");
						return;
					}
					setTimeout(tick, 2500);
				});
		};
		setTimeout(tick, 2500);
	}

	function renderAlmostThere(data, syncStatus) {
		// In-between state for the provisioning-poll timeout. Distinguish
		// from renderSuccess: yellow ring + clearer wording so the
		// customer knows the agent isn't ready yet, plus a Check status
		// button that re-polls. Two ways out:
		//   - Check status -> re-enter pollSyncStatus and either flip to
		//     success or refresh this screen with the current state
		//   - Open Jarvis Settings -> show the Force Resync surface
		state.step = 5;
		renderSteps();
		$footLink.empty();
		const status = (syncStatus || "").trim();
		const label = status.replace(/^pending:\s*/i, "") || "your agent is still warming up";
		$body.html(`
			<div class="jo-success" role="status" aria-live="polite">
			  <div class="jo-success-ring jo-success-ring-warn" style="background:#f59e0b">⌛</div>
			  <h2 class="jo-h">Almost there</h2>
			  <p class="jo-sub">${esc(state.company)}'s container is still spinning up - ${esc(label)}. This is normal on a busy day; the agent usually catches up within another minute or two.</p>
			  <div class="jo-actions jo-actions-split">
			    <button class="jo-btn jo-btn-ghost" id="jo-almost-settings">Open Jarvis Settings</button>
			    <button class="jo-btn jo-btn-primary" id="jo-almost-check">Check status</button>
			  </div>
			</div>`);
		$body.find("#jo-almost-check").on("click", () => {
			setBusy("#jo-almost-check", true);
			frappe.call({ method: "jarvis.onboarding.get_llm_sync_status" })
				.then((r) => {
					const m = r.message || {};
					const s = (m.last_sync_status || "").trim();
					if (!m.pending) {
						renderSuccess(data, s);
						return;
					}
					setBusy("#jo-almost-check", false);
					// Update inline so the customer sees the latest status
					// without re-rendering the whole screen.
					renderAlmostThere(data, s || "pending: container still provisioning");
				})
				.catch(() => {
					setBusy("#jo-almost-check", false);
					renderAlmostThere(data, "pending: lost contact while provisioning");
				});
		});
		$body.find("#jo-almost-settings").on("click", () => frappe.set_route("Form", "Jarvis Settings"));
	}

	function renderProvisioning(status) {
		const label = (status || "").replace(/^pending:\s*/i, "") || "provisioning your agent";
		$body.html(`
			<div class="jo-success">
			  <div class="jo-success-ring jo-spinner-ring">↻</div>
			  <h2 class="jo-h">Spinning up your Jarvis agent...</h2>
			  <p class="jo-sub">${esc(label.charAt(0).toUpperCase() + label.slice(1))}. This usually takes around 30 seconds.</p>
			  <p class="jo-sub" style="margin-top:8px;font-size:12px;opacity:.7">Don't close this tab.</p>
			</div>`);
	}

	function renderSuccess(data, syncStatus, extra) {
		state.step = 5;
		renderSteps();
		$footLink.empty();
		const url = (data && data.agent_url) || "";
		const sync = (syncStatus || "").trim();
		const syncOk = sync.startsWith("ok");
		const syncSkippedNoCreds = !sync;  // came in via "Skip for now"
		let agentLine;
		if (!url) {
			agentLine = "Your container is being prepared - it'll be ready shortly.";
		} else if (syncOk) {
			agentLine = "Your agent is ready.";
		} else if (syncSkippedNoCreds) {
			agentLine = "Your agent is ready - finish connecting your AI in Jarvis Settings to start chatting.";
		} else {
			agentLine = `Your agent is set up, but the AI connection didn't sync just now (<i>${esc(sync)}</i>). Open Jarvis Settings → Force Resync to retry.`;
		}
		const connectedEmail = (extra && extra.connectedEmail) || "";
		const connectedLine = connectedEmail
			? `<p class="jo-sub" style="margin-top:8px">Connected as <b>${esc(connectedEmail)}</b>.</p>`
			: "";
		$body.html(`
			<div class="jo-success">
			  <div class="jo-success-ring">✓</div>
			  <h2 class="jo-h">You're connected!</h2>
			  <p class="jo-sub">Jarvis is set up for <b>${esc(state.company)}</b>. ${agentLine}</p>
			  ${connectedLine}
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
			.then((r) => {
				const d = r.message || {};
				// Admin's require_email_verification flag steers the response
				// shape. When the flag is ON, signup returns no razorpay_order_id
				// and instead asks the customer to click a magic link emailed
				// to their address. The wizard switches to a "check your email"
				// screen + a poll-the-admin button until the link has been
				// clicked, at which point we transition to Razorpay Checkout.
				// Flag OFF (legacy) = response carries razorpay_order_id and
				// we go straight to Checkout, unchanged.
				if (d.pending_verification) {
					renderVerifyEmail();
					return;
				}
				openCheckout(d);
			})
			.catch((e) => payErr(e));
	}

	function renderVerifyEmail() {
		setBusy("#jo-pay", false);
		$body.html(`
			<div class="jo-verify">
				<h2 class="jo-h">Check your email</h2>
				<p class="jo-sub">We sent a confirmation link to <strong>${esc(state.email)}</strong>.
				Click the link to verify your address, then come back here and click
				the button below to continue to payment.</p>
				<p class="jo-sub">The link expires in 24 hours. Check your spam folder if
				it doesn't arrive.</p>
				<div class="jo-err" id="jo-verify-err"></div>
				<div class="jo-actions">
					<button class="jo-btn jo-btn-primary" id="jo-verify-check">I've verified my email →</button>
				</div>
			</div>`);
		$body.find("#jo-verify-check").on("click", () => {
			setBusy("#jo-verify-check", true);
			$body.find("#jo-verify-err").text("");
			frappe.call({ method: "jarvis.onboarding.check_signup_payment_state" })
				.then((r) => {
					const d = r.message || {};
					setBusy("#jo-verify-check", false);
					if (d.pending_verification) {
						$body.find("#jo-verify-err").text(
							"We haven't received your verification yet. Click the link in your email, then try again."
						);
						return;
					}
					if (d.razorpay_order_id) {
						openCheckout(d);
						return;
					}
					// Edge case: subscription already advanced past Pending
					// Payment (e.g. operator manually transitioned, or this
					// is a stale tab). Show a generic message; the next
					// reload picks up the right step.
					$body.find("#jo-verify-err").text(
						"Signup state has changed. Refresh this page to continue."
					);
				})
				.catch((e) => {
					setBusy("#jo-verify-check", false);
					$body.find("#jo-verify-err").text(
						e.message || "Couldn't reach the admin server. Try again."
					);
				});
		});
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
			// Razorpay dismiss (customer closed Checkout without paying).
			// Re-enable Pay AND surface why the wizard didn't advance -
			// the previous shape just re-enabled the button silently,
			// leaving the customer wondering if anything happened.
			// Punch-list item from the 2026-06-16 review.
			modal: {
				ondismiss: () => {
					setBusy("#jo-pay", false);
					frappe.show_alert({
						message: __("Payment cancelled. Click Pay to try again."),
						indicator: "orange",
					});
				},
			},
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
		// frappe.call failures don't reliably carry .message: the .catch
		// receives the raw jqXHR, so server-side frappe.throw text arrives at
		// responseJSON._server_messages (JSON-in-JSON).
		let msg = (e && e.message) || "";
		const sm =
			(e && e._server_messages) ||
			(e && e.responseJSON && e.responseJSON._server_messages) ||
			"";
		if (!msg && sm) {
			try { msg = JSON.parse(JSON.parse(sm)[0] || "{}").message || ""; } catch (x) { /* keep fallback */ }
		}
		$body.find("#jo-pay-err").text(msg || "Something went wrong. Please try again.");
	}

	function setBusy(sel, on) {
		const $b = $body.find(sel);
		// Re-entry guard: a second busy(true) would snapshot the spinner as
		// data-label, so the restore would put the spinner back forever.
		if (on) { if ($b.prop("disabled")) return; $b.prop("disabled", true).attr("data-label", $b.html()).html(`<span class="jo-spin"></span> Working…`); }
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
		//
		// The chat-ui settings call carries the subscription catalogue +
		// per-provider defaults (jarvis/_subscription_models.py). Fired
		// alongside is_onboarded so the picker is populated before the
		// customer ever lands on the Connect AI step. If it fails (rare;
		// frappe.call retries 3xx + auth), the maps stay empty and
		// renderSubscriptionPanel shows the Loading… placeholder, which
		// is preferable to silently mounting a hardcoded fallback that
		// could drift from the Python allowlist.
		Promise.all([
			frappe.call({ method: "jarvis.account.is_onboarded" }),
			frappe.call({ method: "jarvis.chat.api.get_chat_ui_settings" })
				.catch(() => ({ message: {} })),
			frappe.call({ method: "jarvis.onboarding.get_preset_catalog" }).catch(() => ({ message: [] })),
		]).then(([onboarded, chatUi, catalog]) => {
			const cui = (chatUi && chatUi.message) || {};
			subscriptionModels = cui.subscription_models || {};
			defaultModels = cui.default_models || {};
			presetCatalog = (catalog && catalog.message) || [];
			// Seed the default for the initial subProvider so the AI
			// step doesn't open with an empty model dropdown.
			state.subModel = defaultModels[state.subProvider]
				|| (subscriptionModels[state.subProvider] || [])[0]
				|| "";
			if (onboarded && onboarded.message && onboarded.message.onboarded) {
				renderCompletionCard();
				return;
			}
			// Not managed-onboarded. A self-hosted bench with a validated
			// connection is also "set up" - is_ready_for_chat recognizes
			// it - so show the completion card instead of the chooser.
			frappe.call({ method: "jarvis.account.is_ready_for_chat" })
				.then((rr) => {
					if (rr && rr.message && rr.message.ready) renderCompletionCard();
					else render();
				})
				.catch(() => render());
		}).catch(() => render());
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
		.jo-prop-text{flex:1;min-width:0}
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
		/* Company as a Frappe Link control - blend it into the wizard */
		#jo-company-wrap .frappe-control,#jo-company-wrap .form-group{margin:0}
		#jo-company-wrap .control-label,#jo-company-wrap .help-box{display:none}
		#jo-company-wrap input.form-control{width:100%;padding:10px 12px;font-size:14px;height:auto;
			border:1px solid var(--border-color);border-radius:var(--border-radius,8px);
			background:var(--control-bg,var(--bg-color));color:var(--text-color)}
		#jo-company-wrap input.form-control:focus{outline:none;border-color:var(--jarvis-primary);
			box-shadow:0 0 0 2px var(--jarvis-primary-faint)}
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
		.jo-spinner-ring{background:rgba(99,102,241,.14);color:var(--jarvis-primary,#5b6bff);animation:jo-spin 1.4s linear infinite}
		.jo-success .jo-actions{justify-content:center}
		.jo-spin{display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,.5);border-top-color:#fff;
			border-radius:50%;animation:jo-spin .6s linear infinite;vertical-align:-1px}
		@keyframes jo-spin{to{transform:rotate(360deg)}}
		.jo-tabs-label{display:block;font-size:11.5px;letter-spacing:.6px;font-weight:600;
			color:var(--text-muted);text-transform:uppercase;margin-bottom:8px}
		.jo-tabs{position:relative;display:flex;width:100%;padding:4px;
			background:var(--bg-color);border:1px solid var(--border-color);border-radius:10px;
			user-select:none}
		.jo-tabs-thumb{position:absolute;top:4px;bottom:4px;left:4px;width:calc(50% - 4px);
			background:var(--card-bg,#fff);border-radius:8px;
			box-shadow:0 1px 2px rgba(0,0,0,.06), 0 0 0 1px rgba(0,0,0,.04);
			transition:transform .28s cubic-bezier(.4,0,.2,1);pointer-events:none}
		.jo-tabs[data-active="subscription"] .jo-tabs-thumb{transform:translateX(100%)}
		.jo-tab{position:relative;z-index:1;flex:1;appearance:none;display:inline-flex;
			align-items:center;justify-content:center;gap:8px;background:transparent;border:0;
			padding:11px 12px;font-size:13.5px;font-weight:500;color:var(--text-muted);
			border-radius:8px;cursor:pointer;transition:color .2s ease;white-space:nowrap}
		.jo-tab svg{opacity:.7;transition:opacity .2s ease}
		.jo-tab:hover{color:var(--text-color)}
		.jo-tab:hover svg{opacity:.95}
		.jo-tab-active{color:var(--jarvis-primary);font-weight:600}
		.jo-tab-active svg{opacity:1}
		.jo-url-row{display:flex;gap:8px;align-items:center}
		.jo-url-text{flex:1;font-family:'Menlo','Monaco',monospace;font-size:11.5px;line-height:1.4;
			padding:8px 10px;background:var(--bg-color);border:1px solid var(--border-color);
			border-radius:6px;white-space:nowrap;overflow-x:auto;color:var(--text-muted);
			display:block;min-width:0}
		.jo-btn-small{padding:6px 12px;font-size:12px;flex:0 0 auto}
		.jo-modes{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:6px}
		.jo-mode{display:flex;flex-direction:column;border:1.5px solid var(--border-color);border-radius:12px;
			padding:18px 16px;background:var(--card-bg);transition:border-color .15s,box-shadow .15s,transform .1s}
		.jo-mode:hover{border-color:var(--jarvis-primary);transform:translateY(-1px)}
		.jo-mode-icon{font-size:26px;line-height:1}
		.jo-mode-name{font-size:16px;font-weight:700;color:var(--text-color);margin:8px 0 10px}
		.jo-mode-feats{list-style:none;padding:0;margin:0 0 16px;flex:1}
		.jo-mode-feats li{display:flex;gap:7px;font-size:12.5px;color:var(--text-color);line-height:1.5;margin-bottom:7px}
		.jo-mode-feats .jo-tick{color:var(--jarvis-primary);font-size:11px;margin-top:2px}
		.jo-mode .jo-btn{width:100%}
		.jo-check{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--text-color);margin-top:4px;cursor:pointer}
		.jo-sh-results{margin:14px 0 4px;font-size:12.5px;line-height:1.7}
		.jo-sh-check{color:var(--text-color)}
		.jo-sh-ok{color:var(--green-700,#15803d);font-weight:600;margin-bottom:4px}
		.jo-sh-bad{color:var(--red-600,#b91c1c);font-weight:600;margin-bottom:4px}
		@media(max-width:760px){.jo-bg{padding:16px 10px}.jo{flex-direction:column;margin:auto}.jo-brand{flex-basis:auto}.jo-panel{padding:26px 22px}.jo-modes{grid-template-columns:1fr}}
		.jo-tabs-3 .jo-tabs-thumb{width:calc(33.333% - 4px)}
		.jo-tabs-3[data-active="preset"] .jo-tabs-thumb{transform:translateX(100%)}
		.jo-tabs-3[data-active="custom"] .jo-tabs-thumb{transform:translateX(200%)}
		.jo-preset-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
		.jo-preset-card{border:1.5px solid var(--border-color);border-radius:12px;padding:14px;cursor:pointer;background:var(--card-bg);transition:border-color .15s,box-shadow .15s}
		.jo-preset-card:hover{border-color:var(--jarvis-primary)}
		.jo-preset-card.selected{border-color:var(--jarvis-primary);box-shadow:0 0 0 2px var(--jarvis-primary-faint)}
		.jo-preset-label{font-size:13px;font-weight:700;color:var(--text-color);margin-bottom:4px}
		.jo-preset-model{font-size:12px;color:var(--text-muted);margin-top:4px}
		.jo-custom-row{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:8px;align-items:center;margin-bottom:8px}
		/* Custom failover rows — per-row API key ⇄ Chat subscription (mirrors jarvis_account.js) */
		.jo-crow{position:relative;border:1px solid var(--border-color);border-radius:10px;padding:12px;margin-bottom:10px;background:var(--card-bg)}
		.jo-crow-tag{position:absolute;top:-9px;left:12px;font-size:10.5px;font-weight:600;letter-spacing:.3px;text-transform:uppercase;color:var(--text-muted);background:var(--card-bg);padding:0 6px}
		.jo-crow-head{display:flex;align-items:center;gap:8px;margin-bottom:10px}
		.jo-crow-move{margin-left:auto;display:flex;gap:4px}
		.jo-cred-toggle{display:inline-flex;border:1px solid var(--border-color);border-radius:8px;overflow:hidden}
		.jo-cred-btn{appearance:none;border:0;background:var(--card-bg);color:var(--text-muted);font-size:12px;font-weight:500;padding:6px 12px;cursor:pointer;transition:background .15s,color .15s}
		.jo-cred-btn:hover{color:var(--text-color)}
		.jo-cred-btn.jo-cred-active{background:var(--jarvis-primary-faint);color:var(--jarvis-primary);font-weight:600}
		.jo-crow-grid{display:grid;grid-template-columns:1fr 1.4fr 1.4fr 1.4fr;gap:8px;align-items:center}
		.jo-crow-grid-sub{grid-template-columns:2fr 1fr 1.2fr}
		.jo-accts{display:flex;flex-direction:column;gap:5px;margin:8px 0}
		.jo-acct{display:flex;align-items:center;gap:8px;padding:5px 9px;border:1px solid rgba(46,189,89,.35);background:rgba(46,189,89,.08);border-radius:6px}
		.jo-acct-dot{font-size:11px;font-weight:600;color:var(--green-700,#1f8d3a)}
		.jo-acct-label{font-size:12.5px;color:var(--text-color)}
		.jo-acct-rm{margin-left:auto;border:1px solid rgba(226,76,76,.35);background:rgba(226,76,76,.10);color:var(--red-600,#c0392b);border-radius:5px;width:22px;height:22px;cursor:pointer;flex:none;font-size:11px}
		.jo-connect{padding:10px;background:var(--bg-color);border:1px solid var(--border-color);border-radius:8px;margin-bottom:8px}
		.jo-connect textarea{resize:vertical}
		@media(max-width:760px){.jo-crow-grid,.jo-crow-grid-sub{grid-template-columns:1fr}}`;
		$(`<style id="jo-styles">${css}</style>`).appendTo(document.head);
	}
};
