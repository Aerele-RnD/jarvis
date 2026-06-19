frappe.ui.form.on("Jarvis Settings", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Test Admin Connection"), () => {
			frappe.call({
				method: "jarvis.diagnostics.ping_admin",
			}).then((r) => {
				const m = r.message || {};
				if (m.ok) {
					const conn = m.connection || {};
					frappe.msgprint({
						title: __("Admin Reachable"),
						message: __("Admin URL: {0}<br>Customer status: {1}<br>Agent URL: {2}", [
							m.admin_url || "?",
							conn.status || "?",
							conn.agent_url || "?",
						]),
						indicator: "green",
					});
				} else {
					frappe.msgprint({
						title: __("Admin Connection Failed ({0})", [m.kind || "error"]),
						message: m.error || "unknown",
						indicator: "red",
					});
				}
			});
		}, __("Diagnostics"));

		frm.add_custom_button(__("Test Agent Connection"), () => {
			frappe.call({
				method: "jarvis.diagnostics.ping_openclaw",
			}).then((r) => {
				const m = r.message || {};
				if (m.ok) {
					frappe.show_alert({
						message: __("Agent Reachable at {0}", [m.agent_url || "?"]),
						indicator: "green",
					});
				} else {
					frappe.msgprint({
						title: __("Agent Connection Failed ({0})", [m.kind || "error"]),
						message: m.error || "unknown",
						indicator: "red",
					});
				}
			});
		}, __("Diagnostics"));

		// DEV-only reset: visible when sandbox mode is on AND caller is
		// System Manager. The server re-checks both gates - is_dev_mode_active
		// resolves "sandbox mode" through jarvis.dev.is_sandbox_mode (which
		// reads Jarvis Settings.sandbox_mode, with legacy frappe.conf.
		// developer_mode as a one-release fallback).
		frappe.call({ method: "jarvis.dev.is_dev_mode_active" }).then((r) => {
			if (!(r && r.message && r.message.data && r.message.data.active)) return;
			frm.add_custom_button(__("Reset onboarding (DEV)"), () => {
				confirmAndReset(frm);
			}, __("Diagnostics"));
		});

		frm.add_custom_button(__("Force Resync"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Force Resync"),
				fields: [
					{
						fieldname: "action", fieldtype: "Select", label: "Action",
						options: "reload\nrestart", default: "reload", reqd: 1,
						description: __("reload = hot-swap LLM key only. restart = re-render config and bounce the container."),
					},
				],
				primary_action_label: __("Resync Now"),
				primary_action(values) {
					frappe.call({
						method: "jarvis.diagnostics.force_resync",
						args: { action: values.action },
					}).then((r) => {
						const m = r.message || {};
						const ok = (m.last_sync_status || "").startsWith("ok");
						frappe.msgprint({
							title: ok ? __("Resync OK") : __("Resync Reported a Problem"),
							message: __("Action: {0}<br>At: {1}<br>Status: {2}", [
								m.action || "?",
								m.last_sync_at || "(no timestamp)",
								m.last_sync_status || "(no status)",
							]),
							indicator: ok ? "green" : "red",
						});
						frm.reload_doc();
					});
					d.hide();
				},
			});
			d.show();
		}, __("Diagnostics"));

		// ---- Self-Hosted openclaw -----------------------------------------
		frm.add_custom_button(__("Configure Self-Hosted openclaw"), () => {
			openSelfHostDialog(frm);
		}, __("Deployment"));

		if ((frm.doc.deployment_mode || "Managed") === "Self-Hosted") {
			frm.add_custom_button(__("Switch to Managed"), () => {
				frappe.confirm(
					__("Switch back to Aerele-managed openclaw? This re-syncs the managed connection."),
					() => {
						frappe.call({ method: "jarvis.selfhost.switch_to_managed" }).then(() => {
							frappe.show_alert({ message: __("Switched to Managed."), indicator: "green" });
							frm.reload_doc();
						});
					},
				);
			}, __("Deployment"));
		}
	},
});

function renderSelfHostResults(d, result) {
	const checks = result.checks || [];
	const rows = checks
		.map((c) => `<li>${c.ok ? "✅" : "❌"} <b>${frappe.utils.escape_html(c.check)}</b> — ${frappe.utils.escape_html(c.detail || "")}</li>`)
		.join("");
	const overall = result.ok
		? `<div style="color:#1f8a3b;font-weight:600">All required checks passed.</div>`
		: `<div style="color:#b00020;font-weight:600">Some checks failed.</div>`;
	d.fields_dict.results.$wrapper.html(
		`${overall}<ul style="padding-left:18px;margin-top:6px">${rows || "<li>(no checks)</li>"}</ul>`,
	);
}

function openSelfHostDialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Connect Self-Hosted openclaw"),
		fields: [
			{ fieldtype: "HTML", fieldname: "intro",
			  options: `<p>Point Jarvis at <b>your own openclaw server</b>. You bring openclaw and your
				LLM; Jarvis connects over HTTP with a bearer token (no Aerele persona/skills).
				Validate first, then connect.</p>` },
			{ fieldtype: "Data", fieldname: "base_url", label: __("openclaw URL"), reqd: 1,
			  default: (frm.doc.deployment_mode === "Self-Hosted" ? frm.doc.agent_url : "") || "",
			  description: __("e.g. http://host.docker.internal:19060 or https://openclaw.example.com") },
			{ fieldtype: "Password", fieldname: "token", label: __("Gateway Token"), reqd: 1 },
			{ fieldtype: "Check", fieldname: "deep", label: __("Run deep chat test (slower — sends one message)"), default: 0 },
			{ fieldtype: "Button", fieldname: "test_btn", label: __("Test connection") },
			{ fieldtype: "HTML", fieldname: "results" },
		],
		primary_action_label: __("Connect"),
		primary_action(values) {
			d.disable_primary_action();
			frappe.call({
				method: "jarvis.selfhost.save_self_hosted",
				args: { base_url: values.base_url, token: values.token, deep: values.deep ? 1 : 0 },
			}).then((r) => {
				const m = r.message || {};
				if (m.ok) {
					d.hide();
					frappe.show_alert({ message: __("Connected to self-hosted openclaw."), indicator: "green" });
					frm.reload_doc();
				} else {
					renderSelfHostResults(d, m.result || {});
					frappe.msgprint({ title: __("Validation failed"),
						message: __("Fix the failing checks below, then retry."), indicator: "red" });
					d.enable_primary_action();
				}
			}).catch(() => d.enable_primary_action());
		},
	});
	d.fields_dict.test_btn.$input.on("click", () => {
		const v = d.get_values(true);
		if (!v.base_url) { frappe.msgprint(__("Enter the openclaw URL first.")); return; }
		d.fields_dict.results.$wrapper.html(`<div class="text-muted">${__("Testing…")}</div>`);
		frappe.call({
			method: "jarvis.selfhost.test_connection",
			args: { base_url: v.base_url, token: v.token || "", deep: v.deep ? 1 : 0 },
		}).then((r) => renderSelfHostResults(d, r.message || {}))
		  .catch(() => d.fields_dict.results.$wrapper.html(`<div style="color:#b00020">Test call failed.</div>`));
	});
	d.show();
}

function confirmAndReset(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Reset onboarding (irreversible)"),
		fields: [
			{ fieldtype: "HTML", fieldname: "warn",
			  options: `<p>This clears local connection + LLM credentials so the onboarding
				wizard restarts from step 1:</p>
				<ul>
				  <li>Admin API key &amp; secret</li>
				  <li>Agent URL, token, container paths</li>
				  <li>Chat device pairing (keys + token)</li>
				  <li>LLM model / API key / base URL (provider resets to Anthropic)</li>
				  <li>Last sync timestamp + status</li>
				</ul>
				<p>Preserved: Admin URL, monthly budget, sampling settings.</p>
				<p>Does NOT touch admin-side records - use the admin's
				<i>Purge customer (DEV)</i> button for that.</p>
				<p>Type <b>RESET</b> to confirm:</p>` },
			{ fieldtype: "Data", fieldname: "confirm", label: __("Confirm"), reqd: 1 },
		],
		primary_action_label: __("Reset"),
		primary_action(values) {
			if ((values.confirm || "").trim() !== "RESET") {
				frappe.msgprint({ message: __("Type RESET exactly to confirm."), indicator: "red" });
				return;
			}
			d.disable_primary_action();
			frappe.call({ method: "jarvis.dev.reset_onboarding" }).then((r) => {
				d.hide();
				const n = ((r && r.message && r.message.data && r.message.data.cleared_fields) || []).length;
				frappe.show_alert({
					message: __("Onboarding reset - cleared {0} field(s). Go to /app/jarvis-onboarding to start fresh.", [n]),
					indicator: "green",
				});
				frm.reload_doc();
			}).catch(() => {
				d.enable_primary_action();
			});
		},
	});
	d.show();
}
