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

		frm.add_custom_button(__("Test Openclaw Connection"), () => {
			frappe.call({
				method: "jarvis.diagnostics.ping_openclaw",
			}).then((r) => {
				const m = r.message || {};
				if (m.ok) {
					frappe.show_alert({
						message: __("Openclaw Reachable at {0}", [m.agent_url || "?"]),
						indicator: "green",
					});
				} else {
					frappe.msgprint({
						title: __("Openclaw Connection Failed ({0})", [m.kind || "error"]),
						message: m.error || "unknown",
						indicator: "red",
					});
				}
			});
		}, __("Diagnostics"));

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
