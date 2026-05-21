frappe.pages["jarvis-onboarding"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: "Connect to Jarvis", single_column: true });
	const $b = $('<div class="jarvis-onboarding" style="padding:12px;max-width:560px">').appendTo(page.main);
	const dev = !!frappe.boot.developer_mode;

	if (!dev && !window.Razorpay) {
		frappe.require("https://checkout.razorpay.com/v1/checkout.js");
	}

	$b.html(`
		<p>Connect this site to Jarvis Cloud.</p>
		<div class="form-group"><label>Email</label><input class="form-control" id="ob-email"></div>
		<div class="form-group"><label>Company</label><input class="form-control" id="ob-company"></div>
		<div class="form-group"><label>Plan</label><select class="form-control" id="ob-plan"></select></div>
		<button class="btn btn-primary" id="ob-go">${dev ? "Dev signup + connect" : "Sign up & pay"}</button>
		<button class="btn btn-default" id="ob-sync">Sync connection</button>
		<pre id="ob-out" class="mt-3" style="white-space:pre-wrap"></pre>`);

	const out = (m) => $b.find("#ob-out").text(typeof m === "string" ? m : JSON.stringify(m, null, 2));

	frappe.call({ method: "jarvis.onboarding.list_plans" }).then((r) => {
		const sel = $b.find("#ob-plan").empty();
		(r.message || []).forEach((p) =>
			sel.append(`<option value="${p.name}">${frappe.utils.escape_html(p.plan_name)} (${p.billing_cycle}, ₹${p.price_inr})</option>`));
	}).catch((e) => out("Could not load plans: " + (e.message || e)));

	$b.find("#ob-sync").on("click", () =>
		frappe.call({ method: "jarvis.onboarding.sync_connection" }).then((r) => out(r.message)));

	$b.find("#ob-go").on("click", () => {
		const email = $b.find("#ob-email").val();
		const company = $b.find("#ob-company").val();
		const plan = $b.find("#ob-plan").val();
		if (dev) {
			frappe.call({ method: "jarvis.onboarding.dev_onboard", args: { email, company, plan } })
				.then((r) => out(r.message)).catch((e) => out(e.message || "failed"));
			return;
		}
		frappe.call({ method: "jarvis.onboarding.start_signup", args: { email, company, plan } }).then((r) => {
			const d = r.message || {};
			const rz = new Razorpay({
				key: d.razorpay_key_id,
				order_id: d.razorpay_order_id,
				subscription_id: d.razorpay_subscription_id,
				name: "Jarvis",
				handler: (res) =>
					frappe.call({
						method: "jarvis.onboarding.finish_payment",
						args: { payload: {
							razorpay_payment_id: res.razorpay_payment_id,
							razorpay_order_id: res.razorpay_order_id,
							razorpay_signature: res.razorpay_signature,
							razorpay_subscription_id: res.razorpay_subscription_id,
						} },
					}).then((rr) => out(rr.message)),
			});
			rz.open();
		}).catch((e) => out(e.message || "signup failed"));
	});
};
