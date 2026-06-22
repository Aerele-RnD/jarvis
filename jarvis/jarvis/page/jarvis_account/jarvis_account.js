frappe.pages["jarvis-account"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: "My Jarvis Account", single_column: true });
	if (!window.Razorpay) {
		frappe.require("https://checkout.razorpay.com/v1/checkout.js");
	}

	injectStyles();

	const esc = frappe.utils.escape_html;
	const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");
	const cycleLabel = (c) => (String(c).toLowerCase() === "annual" ? "/year" : "/month");

	// LLM provider defaults - mirror the onboarding wizard's PROVIDER_DEFAULTS
	// so the section behaves identically there and here.
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

	// Subscription providers + models (chat-subscription OAuth path).
	// Populated by loadInitial() via jarvis.chat.api.get_chat_ui_settings -
	// the canonical catalogue lives in jarvis/_subscription_models.py, so
	// the JS side is a pure consumer and never drifts from the Python /
	// security allowlist (jarvis.oauth.api validates against the same dict).
	// Until the fetch lands, the maps are empty and renderSubscriptionPanel
	// renders the loading placeholder. Punch-list "_SUBSCRIPTION_MODELS
	// duplicated 4-5 times" from the 2026-06-16 cross-repo review.
	let subscriptionModels = {};
	let defaultModels = {};

	// AI provider card state.
	// aiTab follows llm_auth_mode by default; can diverge briefly while
	// the user is exploring (e.g. on api_key but previewing subscription).
	// sub* holds in-flight paste-back state during sign-in.
	const ui = {
		aiTab: "api_key",
		subProvider: "OpenAI",
		// Populated from defaultModels[subProvider] once
		// loadInitial fetches the catalogue. Empty until then so a
		// stale ui.subModel can't sneak into a paste-back signin
		// before the canonical Python set has been confirmed.
		subModel: "",
		subNonce: null,
		subAuthorizeUrl: null,   // shown to the customer in Screen 2
		subExpiresAt: null,
	};

	// ---- helpers -----------------------------------------------------------
	// Copy text to clipboard with a graceful fallback for insecure contexts
	// (HTTP / non-localhost). Returns a Promise that resolves on success,
	// rejects on failure so callers can show honest feedback. Customers
	// reach /jarvis-account over LAN HTTP where navigator.clipboard is
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

	// ---- boot --------------------------------------------------------------
	loadInitial();

	function loadInitial() {
		$body.html(`<div class="ja-loading">Loading your account…</div>`);
		frappe.call({ method: "jarvis.selfhost.get_status" })
			.then((st) => {
				// Self-hosted benches have no admin signup, so is_onboarded
				// is false for them - render the self-host connection view
				// instead of bouncing to the onboarding wizard.
				if ((st && st.message && st.message.deployment_mode) === "Self-Hosted") {
					renderSelfHostAccount(st.message);
					return null;
				}
				return frappe.call({ method: "jarvis.account.is_onboarded" });
			})
			.then((r) => {
				if (r === null) return;  // self-hosted view already rendered
				if (!r.message || !r.message.onboarded) {
					// Not onboarded - wizard owns this customer.
					window.location.assign("/app/jarvis-onboarding");
					return;
				}
				return Promise.all([
					frappe.call({ method: "jarvis.account.get_account" }),
					frappe.db.get_doc("Jarvis Settings"),
					frappe.call({ method: "jarvis.chat.api.get_chat_ui_settings" }),
				]).then(([acc, settings, chatUi]) => {
					account = (acc && acc.message) || {};
					settingsLocal = settings || {};
					const cui = (chatUi && chatUi.message) || {};
					subscriptionModels = cui.subscription_models || {};
					defaultModels = cui.default_models || {};
					// First-paint seed: pick the canonical default for the
					// initial subProvider so render() doesn't show an empty
					// model dropdown before the user has touched anything.
					ui.subModel = defaultModels[ui.subProvider]
						|| (subscriptionModels[ui.subProvider] || [])[0]
						|| "";
					ui.aiTab = settingsLocal.llm_auth_mode === "oauth" ? "subscription" : "api_key";
					// In oauth mode, seed sub-state from the saved provider/model so
					// a Re-authorize click uses THIS customer's provider (e.g.
					// "Google Gemini") instead of the hardcoded default that the
					// api_key→subscription wizard path uses.
					// Carry-over guards: only adopt llm_provider if it's still a
					// known subscription provider, and only adopt llm_model if it
					// matches a codex-CLI model for that provider. A standard-API
					// model (e.g. "gpt-4o") going through codex auth makes
					// openclaw fail every chat turn with "No API key found".
					// jarvis.oauth.api._coerce_subscription_model server-side
					// catches this too; this is just so the dropdown + the
					// "Sign in with ..." button label stay consistent.
					if (settingsLocal.llm_auth_mode === "oauth") {
						if (settingsLocal.llm_provider && subscriptionModels[settingsLocal.llm_provider]) {
							ui.subProvider = settingsLocal.llm_provider;
						}
						const valid = subscriptionModels[ui.subProvider] || [];
						if (settingsLocal.llm_model && valid.includes(settingsLocal.llm_model)) {
							ui.subModel = settingsLocal.llm_model;
						} else {
							ui.subModel = valid[0] || ui.subModel;
						}
					}
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

	// ---- self-hosted connection view --------------------------------------
	function renderShChecks($container, result) {
		const checks = result.checks || [];
		const rows = checks.map((c) =>
			`<div>${c.ok ? "✅" : "❌"} <b>${esc(c.check)}</b> — ${esc(c.detail || "")}</div>`).join("");
		const overall = result.ok
			? `<div style="color:var(--green-700,#15803d);font-weight:600">All required checks passed.</div>`
			: `<div style="color:var(--red-600,#b91c1c);font-weight:600">Some checks failed.</div>`;
		$container.html(overall + rows);
	}

	function renderSelfHostAccount(st) {
		const row = (k, v) => `<div style="display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid var(--border-color);font-size:13px"><span style="color:var(--text-muted)">${k}</span><b>${esc(v || "-")}</b></div>`;
		$body.html(`
			<div class="ja-card">
			  <div class="ja-eyebrow">Connection</div>
			  <div class="ja-card-head" style="margin-bottom:14px">
			    <h2 class="ja-h">Self-hosted openclaw</h2>
			    <span class="ja-pill ja-pill-ok">Self-hosted</span>
			  </div>
			  <p class="ja-sub">Jarvis is connected to <b>your own</b> openclaw server. You manage openclaw and the LLM. Switch to Aerele-managed anytime.</p>
			  ${row("openclaw URL", st.agent_url)}
			  ${row("Last validated", st.validated_at)}
			  <div id="ja-sh-results" style="margin:12px 0;font-size:12.5px;line-height:1.7"></div>
			  <div class="ja-err" id="ja-sh-err"></div>
			  <div style="display:flex;gap:10px;margin-top:16px;flex-wrap:wrap">
			    <button class="ja-btn ja-btn-ghost" id="ja-sh-test">Test connection</button>
			    <button class="ja-btn ja-btn-ghost" id="ja-sh-recfg">Reconfigure</button>
			    <button class="ja-btn ja-btn-primary" id="ja-sh-managed">Switch to managed</button>
			  </div>
			</div>`);
		const $err = $body.find("#ja-sh-err");
		const $res = $body.find("#ja-sh-results");
		$body.find("#ja-sh-test").on("click", () => {
			$err.text(""); $res.html(`<div style="color:var(--text-muted)">Testing…</div>`);
			frappe.call({ method: "jarvis.selfhost.test_connection", args: { base_url: st.agent_url, token: "", deep: 0 } })
				.then((r) => renderShChecks($res, r.message || {}))
				.catch((e) => $err.text(e.message || "Test failed."));
		});
		$body.find("#ja-sh-recfg").on("click", () => openSelfHostReconfigure(st));
		$body.find("#ja-sh-managed").on("click", () => {
			frappe.confirm(
				__("Switch back to Aerele-managed openclaw? This re-syncs the managed connection."),
				() => frappe.call({ method: "jarvis.selfhost.switch_to_managed" }).then(() => {
					frappe.show_alert({ message: __("Switched to managed."), indicator: "green" });
					loadInitial();
				}));
		});
	}

	function openSelfHostReconfigure(st) {
		const d = new frappe.ui.Dialog({
			title: __("Reconfigure self-hosted openclaw"),
			fields: [
				{ fieldtype: "Data", fieldname: "base_url", label: __("openclaw URL"), reqd: 1, default: st.agent_url || "" },
				{ fieldtype: "Password", fieldname: "token", label: __("Gateway token"), reqd: 1 },
				{ fieldtype: "Check", fieldname: "stream", label: __("Stream responses token-by-token"), default: st.stream === false ? 0 : 1, description: __("Off = full reply at once; use if a proxy buffers SSE.") },
				{ fieldtype: "Button", fieldname: "test_btn", label: __("Test connection") },
				{ fieldtype: "HTML", fieldname: "results" },
			],
			primary_action_label: __("Save"),
			primary_action(v) {
				d.disable_primary_action();
				frappe.call({ method: "jarvis.selfhost.save_self_hosted", args: { base_url: v.base_url, token: v.token, deep: 0, stream: v.stream ? 1 : 0 } })
					.then((r) => {
						const m = r.message || {};
						if (m.ok) { d.hide(); frappe.show_alert({ message: m.warning ? __(m.warning) : __("Saved."), indicator: m.warning ? "orange" : "green" }, m.warning ? 15 : undefined); loadInitial(); }
						else { renderShChecks(d.fields_dict.results.$wrapper, m.result || {}); d.enable_primary_action(); }
					}).catch(() => d.enable_primary_action());
			},
		});
		d.fields_dict.test_btn.$input.on("click", () => {
			const v = d.get_values(true);
			if (!v.base_url) { frappe.msgprint(__("Enter the openclaw URL.")); return; }
			d.fields_dict.results.$wrapper.html(`<div class="text-muted">${__("Testing…")}</div>`);
			frappe.call({ method: "jarvis.selfhost.test_connection", args: { base_url: v.base_url, token: v.token || "", deep: 0 } })
				.then((r) => renderShChecks(d.fields_dict.results.$wrapper, r.message || {}));
		});
		d.show();
	}

	function render() {
		const sub = account.subscription_status || "none";
		const editable = EDITABLE_STATES.has(sub);
		$body.html(`
			${renderPlanSection()}
			${renderAiProviderCard(editable)}
			${renderBillingSection()}
		`);
		bindAiProviderCard(editable);
		bindBilling();
	}

	// ---- AI provider card (tabbed: API key | Chat subscription) ----------
	// Segmented-control style - full-width container, sliding thumb between
	// the two halves, equal-width buttons. Click handler swaps only the
	// panel body so the slide animation isn't interrupted by a full
	// re-render of the tabs DOM.
	const ICON_KEY = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>`;
	const ICON_CHAT = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`;

	function renderAiProviderCard(editable) {
		const provider = settingsLocal.llm_provider || "-";
		const inApiKeyMode = settingsLocal.llm_auth_mode !== "oauth";
		const tabs = `
			<label class="ja-tabs-label">Authentication mode</label>
			<div class="ja-tabs" role="tablist" data-active="${ui.aiTab}">
				<span class="ja-tabs-thumb" aria-hidden="true"></span>
				<button type="button" class="ja-tab ${ui.aiTab === "api_key" ? "ja-tab-active" : ""}"
					data-tab="api_key" role="tab" aria-selected="${ui.aiTab === "api_key"}">
					${ICON_KEY}<span>API key</span>
				</button>
				<button type="button" class="ja-tab ${ui.aiTab === "subscription" ? "ja-tab-active" : ""}"
					data-tab="subscription" role="tab" aria-selected="${ui.aiTab === "subscription"}">
					${ICON_CHAT}<span>Chat subscription</span>
				</button>
			</div>`;
		const body = ui.aiTab === "api_key"
			? renderApiKeyPanel(editable, inApiKeyMode)
			: renderSubscriptionPanel(editable, !inApiKeyMode);
		return `<div class="ja-card">
			<div class="ja-eyebrow">AI provider</div>
			<div class="ja-card-head" style="margin-bottom:18px">
				<h2 class="ja-h">How Jarvis talks to your LLM</h2>
				${!inApiKeyMode ? `<span class="ja-pill ja-pill-ok">${esc(provider)}</span>` : ""}
			</div>
			${tabs}
			<div class="ja-tab-body">${body}</div>
		</div>`;
	}

	function renderApiKeyPanel(editable, isActiveMode) {
		const provider = settingsLocal.llm_provider || "Anthropic";
		const model = settingsLocal.llm_model || (PROVIDER_DEFAULTS[provider] || {}).model || "";
		const base = settingsLocal.llm_base_url || (PROVIDER_DEFAULTS[provider] || {}).baseUrl || "";
		const sync = settingsLocal.last_sync_status || "";
		const dis = editable ? "" : "disabled";
		const sel = PROVIDERS.map((p) => `<option value="${esc(p)}" ${p === provider ? "selected" : ""}>${esc(p)}</option>`).join("");
		// Sprint-4 punch-list "frappe.confirm consent for destructive
		// subscription→api-key switch bypassable via Save": when the
		// customer is on the api_key tab while still in oauth mode, show
		// a danger-styled banner that names the connected account (so
		// they can tell exactly which session is about to be cut) and
		// makes the Save button danger-coloured. The actual destructive
		// confirm fires in bindLlm at click time via frappe.warn.
		const connectedEmail = settingsLocal.llm_oauth_account_email || "";
		const emailLine = connectedEmail
			? ` Currently connected as <b>${esc(connectedEmail)}</b>.`
			: "";
		const notice = !isActiveMode
			? `<div class="ja-banner ja-banner-danger">⚠ You're currently using a chat subscription.${emailLine} Saving credentials here will switch you to API-key mode and disconnect the subscription.</div>`
			: "";
		// Save button gets the danger variant when we're about to act
		// destructively. Keeps the primary variant for the normal case
		// (already in api_key mode and just updating the key / model).
		const saveBtnClass = !isActiveMode ? "ja-btn-danger" : "ja-btn-primary";
		const saveBtnLabel = !isActiveMode ? "Disconnect &amp; switch to API key" : "Save credentials";
		return `
			<p class="ja-sub">Your API key is sent directly to the provider - Jarvis only relays prompts.</p>
			${notice}
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
				<button class="ja-btn ${saveBtnClass}" id="ja-llm-save" ${dis}>${saveBtnLabel}</button>
				<span class="ja-llm-status">${sync ? "Last sync: " + esc(sync) : ""}</span>
			</div>
			<div class="ja-err" id="ja-llm-err"></div>`;
	}

	function renderSubscriptionPanel(editable, isActiveMode) {
		// Screen 2 - authorize URL shown, awaiting paste-back. Wins over
		// Screen 3 so that Re-authorize (in oauth mode) actually swaps to
		// the paste-back UI. Without this, the isActiveMode short-circuit
		// re-renders Screen 3 and the new subAuthorizeUrl is invisible.
		if (ui.subAuthorizeUrl) {
			const minsLeft = Math.max(0, Math.floor((ui.subExpiresAt - Date.now()) / 60000));
			return `
				<p class="ja-sub"><strong>Step 1</strong> - Sign in with your ${esc(ui.subProvider)} account in a new tab.</p>
				<div class="ja-actions" style="margin-bottom:10px">
					<button class="ja-btn ja-btn-primary" id="ja-sub-open-url">Open Sign-in URL →</button>
				</div>
				<div class="ja-url-row" style="margin-bottom:18px">
					<code class="ja-url-text" id="ja-sub-url-text" title="${esc(ui.subAuthorizeUrl)}">${esc(ui.subAuthorizeUrl)}</code>
					<button type="button" class="ja-btn ja-btn-ghost ja-btn-small" id="ja-sub-copy-url" title="Copy URL">Copy</button>
				</div>
				<p class="ja-sub"><strong>Step 2</strong> - After clicking Authorize, your browser will show a page saying <em>"This site can't be reached."</em> <strong>That's expected.</strong> Copy the URL from your browser's address bar (it'll start with <code>http://localhost:1455/auth/callback?code=…</code>) and paste it here:</p>
				<div class="ja-field">
					<textarea class="ja-input" id="ja-sub-pasted-url" rows="3" placeholder="Paste the URL from the error page here"></textarea>
				</div>
				<div class="ja-actions">
					<button class="ja-btn ja-btn-ghost" id="ja-sub-cancel">Cancel</button>
					<button class="ja-btn ja-btn-primary" id="ja-sub-submit">Submit →</button>
				</div>
				<div class="ja-hint" style="margin-top:14px;font-size:12px;color:var(--text-muted)">Link valid for ~${minsLeft} minute${minsLeft === 1 ? "" : "s"}.</div>
				<div class="ja-err" id="ja-sub-err"></div>`;
		}
		// Screen 3 - already connected (oauth mode, no in-flight Re-authorize).
		if (isActiveMode) {
			const provider = settingsLocal.llm_provider || "-";
			const model = settingsLocal.llm_model || "-";
			const email = settingsLocal.llm_oauth_account_email || "-";
			// frappe.datetime.comment_when returns a <span class="frappe-timestamp">
			// HTML widget (with hover tooltip). DON'T escape - let it render
			// as live HTML. Other fields are plain strings; keep esc() on them.
			const connectedAtHtml = settingsLocal.llm_oauth_connected_at
				? frappe.datetime.comment_when(settingsLocal.llm_oauth_connected_at)
				: "-";
			return `
				<p class="ja-sub">Refresh and account state live inside your Jarvis container. If chat starts failing, click Re-authorize to mint fresh tokens.</p>
				<table class="ja-kv">
					<tr><td>Account</td><td>${esc(email)}</td></tr>
					<tr><td>Provider</td><td>${esc(provider)}</td></tr>
					<tr><td>Model</td><td>${esc(model)}</td></tr>
					<tr><td>Connected</td><td>${connectedAtHtml}</td></tr>
				</table>
				<div class="ja-actions">
					<button class="ja-btn ja-btn-ghost" id="ja-sub-disconnect">Disconnect</button>
					<button class="ja-btn ja-btn-primary" id="ja-sub-reauth">Re-authorize</button>
				</div>`;
		}
		// Screen 1 - provider + model picker (not yet started)
		const provOptions = Object.keys(subscriptionModels).map(
			(p) => `<option value="${esc(p)}" ${p === ui.subProvider ? "selected" : ""}>${esc(p)}</option>`
		).join("");
		const modelOptions = (subscriptionModels[ui.subProvider] || []).map(
			(m) => `<option value="${esc(m)}" ${m === ui.subModel ? "selected" : ""}>${esc(m)}</option>`
		).join("");
		const dis = editable ? "" : "disabled";
		return `
			<p class="ja-sub">Sign in with your existing ChatGPT Plus / Pro or Gemini Advanced account - no developer key needed.</p>
			<div class="ja-row2">
				<div class="ja-field">
					<label>Provider</label>
					<select id="ja-sub-provider" class="ja-input" ${dis}>${provOptions}</select>
				</div>
				<div class="ja-field">
					<label>Default model</label>
					<select id="ja-sub-model" class="ja-input" ${dis}>${modelOptions}</select>
				</div>
			</div>
			<div class="ja-actions">
				<button class="ja-btn ja-btn-primary" id="ja-sub-signin" ${dis}>Sign in with ${esc(ui.subProvider)} →</button>
			</div>
			<div class="ja-err" id="ja-sub-err"></div>`;
	}

	function bindAiProviderCard(editable) {
		$body.find(".ja-tab").on("click", function () {
			const tab = $(this).data("tab");
			if (tab === ui.aiTab) return;
			handleTabSwitch(tab);
		});
		if (ui.aiTab === "api_key") {
			bindLlm(editable);
		} else {
			bindSubscriptionPanel(editable);
		}
	}

	function handleTabSwitch(targetTab) {
		// Sprint-4 punch-list "frappe.confirm consent for destructive
		// subscription→api-key switch bypassable via Save": the previous
		// shape fired a destructive frappe.confirm here at tab-switch
		// time, BUT bindLlm's save handler unconditionally called
		// save_llm_creds with auth_mode='api_key' regardless of how the
		// user got onto the API-key panel. A customer could cancel the
		// switch confirm, accept the panel preview, then click Save and
		// silently lose their OAuth connection.
		//
		// Now: tab switching is preview-only, no confirm. The destructive
		// consent gate moved to the Save click handler (bindLlm below),
		// uses frappe.warn for danger-styled UI, and shows the previously
		// connected email so the customer knows exactly what's about to
		// be disconnected.
		ui.aiTab = targetTab;
		if (targetTab !== "subscription") cancelSubscriptionFlow();

		// Drive the slide animation by updating data-active on the
		// persistent tabs node. Swap only the panel body (fade out → swap
		// → fade in) instead of re-rendering the whole card, so the slide
		// isn't interrupted by a DOM rebuild.
		const sub = account.subscription_status || "none";
		const editable = EDITABLE_STATES.has(sub);
		const $tabs = $body.find(".ja-tabs");
		$tabs.attr("data-active", targetTab);
		$tabs.find(".ja-tab").each(function () {
			const isActive = $(this).data("tab") === targetTab;
			$(this).toggleClass("ja-tab-active", isActive).attr("aria-selected", isActive);
		});
		const inApiKeyMode = settingsLocal.llm_auth_mode !== "oauth";
		const newBody = targetTab === "api_key"
			? renderApiKeyPanel(editable, inApiKeyMode)
			: renderSubscriptionPanel(editable, !inApiKeyMode);
		const $panel = $body.find(".ja-tab-body");
		$panel.addClass("ja-tab-body-swap");
		setTimeout(() => {
			$panel.html(newBody);
			$panel.removeClass("ja-tab-body-swap");
			if (targetTab === "api_key") bindLlm(editable);
			else bindSubscriptionPanel(editable);
		}, 160);
	}

	function bindSubscriptionPanel(editable) {
		const isActiveMode = settingsLocal.llm_auth_mode === "oauth";
		// Screen 2 wiring must come BEFORE the Screen 3 short-circuit. When
		// Re-authorize is clicked in oauth mode, ui.subAuthorizeUrl gets set,
		// render() emits Screen 2 HTML, and we need to bind its open/copy/
		// cancel/submit handlers - the Screen 3 path returns early, so we
		// have to fall through here when subAuthorizeUrl is set.
		if (ui.subAuthorizeUrl) {
			bindSubscriptionScreen2();
			return;
		}
		if (isActiveMode) {
			$body.find("#ja-sub-disconnect").on("click", () => {
				frappe.confirm(
					__("Disconnect the LLM subscription? Jarvis chat will stop working until you reconnect."),
					() => {
						frappe.call({ method: "jarvis.oauth.api.disconnect" }).then((r) => {
							const m = r.message || {};
							if (m.ok) {
								frappe.show_alert({ message: __("Disconnected."), indicator: "orange" });
								loadInitial();
							} else {
								frappe.show_alert({
									message: (m.error && m.error.message) || __("Disconnect failed."),
									indicator: "red",
								});
							}
						});
					},
				);
			});
			$body.find("#ja-sub-reauth").on("click", () => {
				cancelSubscriptionFlow();
				startCodexSignin();
			});
			return;
		}
		if (!editable) return;
		// Screen 1 wiring
		$body.find("#ja-sub-provider").on("change", (e) => {
			ui.subProvider = e.target.value;
			ui.subModel = (subscriptionModels[ui.subProvider] || [])[0] || "";
			render();
		});
		$body.find("#ja-sub-model").on("change", (e) => {
			ui.subModel = e.target.value;
		});
		$body.find("#ja-sub-signin").on("click", startCodexSignin);
		// Screen 2 wiring - also reachable from Screen 1 -> startCodexSignin.
		bindSubscriptionScreen2();
	}

	function bindSubscriptionScreen2() {
		$body.find("#ja-sub-open-url").on("click", () => {
			if (ui.subAuthorizeUrl) {
				window.open(ui.subAuthorizeUrl, "_blank", "noopener,noreferrer");
			}
		});
		$body.find("#ja-sub-copy-url").on("click", function () {
			if (!ui.subAuthorizeUrl) return;
			const $btn = $(this);
			copyTextWithFallback(ui.subAuthorizeUrl).then(() => {
				const orig = $btn.text();
				$btn.text("Copied ✓");
				setTimeout(() => $btn.text(orig), 1400);
				frappe.show_alert({ indicator: "green", message: __("Sign-in URL copied") });
			}).catch(() => {
				frappe.show_alert({ indicator: "red", message: __("Could not copy - select the URL above and copy manually") });
			});
		});
		$body.find("#ja-sub-cancel").on("click", () => {
			cancelSubscriptionFlow();
			render();
		});
		$body.find("#ja-sub-submit").on("click", submitPastedUrl);
	}

	function startCodexSignin() {
		// $err only exists on Screen 1 and Screen 2. When called from the
		// Screen 3 Re-authorize handler, $err is an empty jQuery set so
		// .text() is a no-op - errors would be silent. surfaceErr() falls
		// back to a frappe.show_alert toast when the in-form error div is
		// missing, so the customer always sees what went wrong.
		const $err = $body.find("#ja-sub-err");
		$err.text("");
		setBusy("#ja-sub-signin", true);
		frappe.call({
			method: "jarvis.oauth.api.begin_paste_signin",
			args: { provider: ui.subProvider, model: ui.subModel },
		}).then((r) => {
			setBusy("#ja-sub-signin", false);
			const m = r.message || {};
			if (!m.ok) {
				surfaceErr($err, (m.error && m.error.message) || "Couldn't start sign-in.");
				return;
			}
			ui.subNonce = m.data.nonce;
			ui.subAuthorizeUrl = m.data.authorize_url;
			ui.subExpiresAt = Date.now() + m.data.expires_in * 1000;
			render();
		}).catch((e) => {
			setBusy("#ja-sub-signin", false);
			surfaceErr($err, e.message || "Couldn't reach Jarvis.");
		});
	}

	function surfaceErr($err, message) {
		if ($err && $err.length) {
			$err.text(message);
		} else {
			frappe.show_alert({ indicator: "red", message: message });
		}
	}

	function submitPastedUrl() {
		const $err = $body.find("#ja-sub-err");
		$err.text("");
		const pasted = ($body.find("#ja-sub-pasted-url").val() || "").trim();
		if (!pasted) {
			$err.text("Paste the URL from your browser's address bar first.");
			return;
		}
		setBusy("#ja-sub-submit", true);
		frappe.call({
			method: "jarvis.oauth.api.complete_paste_signin",
			args: { nonce: ui.subNonce, redirected_url: pasted },
		}).then((r) => {
			setBusy("#ja-sub-submit", false);
			const m = r.message || {};
			if (!m.ok) {
				const errCode = (m.error && m.error.code) || "";
				const errMsg = (m.error && m.error.message) || "Sign-in failed.";
				$err.text(`${errCode}: ${errMsg}`);
				if (errCode === "expired" || errCode === "unknown_nonce") {
					setTimeout(() => { cancelSubscriptionFlow(); render(); }, 2500);
				}
				return;
			}
			frappe.show_alert({ message: "Connected to chat subscription.", indicator: "green" });
			cancelSubscriptionFlow();
			loadInitial();
		}).catch((e) => {
			setBusy("#ja-sub-submit", false);
			$err.text(e.message || "Couldn't reach Jarvis.");
		});
	}

	function cancelSubscriptionFlow() {
		ui.subNonce = null;
		ui.subAuthorizeUrl = null;
		ui.subExpiresAt = null;
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
				return `<div class="ja-banner ja-banner-warn">Plan past due - expired on <b>${esc(end)}</b>. Reactivate to resume service.</div>`;
			case "Expired":
				return `<div class="ja-banner ja-banner-bad">Plan expired on <b>${esc(end)}</b>. Reactivate to resume service.</div>`;
			case "Pending Payment":
				return `<div class="ja-banner ja-banner-warn">Payment incomplete · finish to activate.</div>`;
			default:
				return "";
		}
	}

	// ---- LLM credentials binding (form rendered by renderApiKeyPanel) ----
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

			// Sprint-4 punch-list "frappe.confirm consent for destructive
			// subscription→api-key switch bypassable via Save": when the
			// customer is currently in oauth mode and about to switch to
			// api_key, fire frappe.warn here at click time (the
			// authoritative destructive gate). frappe.warn is the
			// danger-styled variant of frappe.confirm - red Proceed
			// button + warning iconography. Names the connected account
			// so the customer can see exactly which session is about to
			// be cut. If the customer cancels, no save happens; the
			// previous shape moved the confirm to tab-switch time and
			// the Save handler ran unconditionally - a click-cancel-on-
			// tab-switch then click-Save sequence silently dropped the
			// subscription.
			const wasOauth = settingsLocal.llm_auth_mode === "oauth";
			const proceedSave = () => doSaveApiKeyCreds({ provider, model, key, base, wasOauth });
			if (wasOauth) {
				const connectedEmail = settingsLocal.llm_oauth_account_email || "";
				const emailLine = connectedEmail
					? `<p>This will disconnect your chat subscription connected as <b>${frappe.utils.escape_html(connectedEmail)}</b>.</p>`
					: "<p>This will disconnect your chat subscription.</p>";
				frappe.warn(
					__("Disconnect chat subscription?"),
					emailLine
						+ "<p>Your saved API key will be used for chat instead. "
						+ "Reconnecting later means signing in again from the Subscription tab.</p>",
					proceedSave,
					__("Disconnect and switch"),
				);
				return;
			}
			proceedSave();
		});
	}

	function doSaveApiKeyCreds({ provider, model, key, base, wasOauth }) {
		setBusy("#ja-llm-save", true);
		frappe.call({
			method: "jarvis.onboarding.save_llm_creds",
			args: { provider, model, api_key: key || "", base_url: base, auth_mode: "api_key" },
		}).then((r) => {
				const status = (r.message && r.message.last_sync_status) || "";
				// wasOauth was captured in the click handler before frappe.call
				// fired and threaded in via doSaveApiKeyCreds's destructured
				// param so the post-save branch below correctly knows whether
				// to re-render the card.
				settingsLocal.llm_provider = provider;
				settingsLocal.llm_model = model;
				settingsLocal.llm_base_url = base;
				settingsLocal.llm_api_key = key || settingsLocal.llm_api_key;
				settingsLocal.llm_auth_mode = "api_key";
				settingsLocal.last_sync_status = status;
				$body.find("#ja-key").val("");
				// 2026-06-09: on_update is async - the save returns
				// "pending: ..." while the admin restart runs in the
				// background. Poll until the status flips to ok/failed.
				if (status.startsWith("pending:")) {
					$body.find(".ja-llm-status").text("Provisioning... " + status.replace(/^pending:\s*/i, ""));
					pollLlmSyncStatus({ wasOauth });
				} else {
					setBusy("#ja-llm-save", false);
					$body.find(".ja-llm-status").text(status ? "Last sync: " + status : "Saved.");
					// If we just flipped out of oauth mode, re-render so the
					// "current mode" pill and notice banner update correctly.
					if (wasOauth) render();
				}
			}).catch((e) => {
				setBusy("#ja-llm-save", false);
				$body.find("#ja-llm-err").text(e.message || "Save failed.");
			});
	}

	function pollLlmSyncStatus({ wasOauth }) {
		// On_update is async - poll get_llm_sync_status until the status
		// flips from "pending: ..." to "ok ..." / "failed: ...". Admin's
		// healthz timeout is 60s; we cap at 150s for slack.
		const startedAt = Date.now();
		const TIMEOUT_MS = 150 * 1000;
		const tick = () => {
			frappe.call({ method: "jarvis.onboarding.get_llm_sync_status" })
				.then((r) => {
					const m = r.message || {};
					const status = (m.last_sync_status || "").trim();
					settingsLocal.last_sync_status = status;
					if (!m.pending) {
						setBusy("#ja-llm-save", false);
						$body.find(".ja-llm-status").text(status ? "Last sync: " + status : "Saved.");
						if (wasOauth) render();
						return;
					}
					if (Date.now() - startedAt > TIMEOUT_MS) {
						setBusy("#ja-llm-save", false);
						$body.find(".ja-llm-status").text("Still provisioning - check back in a moment.");
						return;
					}
					$body.find(".ja-llm-status").text("Provisioning... " + status.replace(/^pending:\s*/i, ""));
					setTimeout(tick, 2500);
				})
				.catch(() => {
					if (Date.now() - startedAt > TIMEOUT_MS) {
						setBusy("#ja-llm-save", false);
						$body.find(".ja-llm-status").text("Lost contact while provisioning - refresh later.");
						return;
					}
					setTimeout(tick, 2500);
				});
		};
		setTimeout(tick, 2500);
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
						heading: "Want more capacity?", subtitle: "Move to a higher plan - you only pay the prorated difference for the remaining period." }
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
		showOverlay("Payment received - finalizing your account…");
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
						message: "Your payment was received. The page should update within a minute - refresh to view, or contact support if it doesn't.",
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
		/* Segmented control - full-width two-up tab picker with sliding thumb */
		.ja-tabs-label{display:block;font-size:11.5px;letter-spacing:.6px;font-weight:600;
			color:var(--text-muted);text-transform:uppercase;margin-bottom:8px}
		.ja-tabs{position:relative;display:flex;width:100%;padding:4px;margin-bottom:18px;
			background:var(--bg-color);border:1px solid var(--border-color);border-radius:10px;
			user-select:none}
		.ja-tabs-thumb{position:absolute;top:4px;bottom:4px;left:4px;width:calc(50% - 4px);
			background:var(--card-bg,#fff);border-radius:8px;
			box-shadow:0 1px 2px rgba(0,0,0,.06), 0 0 0 1px rgba(0,0,0,.04);
			transition:transform .28s cubic-bezier(.4,0,.2,1);pointer-events:none}
		.ja-tabs[data-active="subscription"] .ja-tabs-thumb{transform:translateX(100%)}
		.ja-tab{position:relative;z-index:1;flex:1;appearance:none;display:inline-flex;
			align-items:center;justify-content:center;gap:8px;background:transparent;border:0;
			padding:11px 12px;font-size:13.5px;font-weight:500;color:var(--text-muted);
			border-radius:8px;cursor:pointer;transition:color .2s ease;white-space:nowrap}
		.ja-tab svg{opacity:.7;transition:opacity .2s ease}
		.ja-tab:hover{color:var(--text-color)}
		.ja-tab:hover svg{opacity:.95}
		.ja-tab-active{color:var(--jarvis-primary);font-weight:600}
		.ja-tab-active svg{opacity:1}
		.ja-tab-body{transition:opacity .14s ease,transform .14s ease}
		.ja-tab-body-swap{opacity:0;transform:translateY(4px)}
		.ja-url-row{display:flex;gap:8px;align-items:center}
		.ja-url-text{flex:1;font-family:'Menlo','Monaco',monospace;font-size:11.5px;line-height:1.4;
			padding:8px 10px;background:var(--bg-color);border:1px solid var(--border-color);
			border-radius:6px;white-space:nowrap;overflow-x:auto;color:var(--text-muted);
			display:block;min-width:0}
		.ja-btn-small{padding:6px 12px;font-size:12px;flex:0 0 auto}
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
		/* Sprint-4 punch-list: danger variant signals destructive action.
		   Used on the api_key Save button when the customer is still in
		   oauth mode (Save will disconnect the subscription). Same shape
		   as ja-btn-primary so layout doesn't jump; red background +
		   white text + accessible contrast on hover.   */
		.ja-btn-danger{background:var(--red-500,#e24c4c);color:#fff}
		.ja-btn-danger:hover{filter:brightness(.92)}
		.ja-btn-danger:disabled{opacity:.5;cursor:not-allowed}
		.ja-banner-danger{background:rgba(226,76,76,.12);color:var(--text-color);border:1px solid rgba(226,76,76,.30);border-radius:var(--border-radius,8px);padding:10px 12px;margin:8px 0 14px}
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
