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

		// DEV-only reset: visible when developer_mode is on AND caller is
		// System Manager. The server re-checks both gates.
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
	},
});

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
				<p>Does NOT touch admin-side records — use the admin's
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
					message: __("Onboarding reset — cleared {0} field(s). Go to /app/jarvis-onboarding to start fresh.", [n]),
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
