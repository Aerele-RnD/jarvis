<template>
	<div class="jv-settings-body">
		<!-- ===== Plan & billing (design.md §4.2 — the dialog header owns the
		     pane title; this pane renders the current-plan block, the upgrade
		     cards and the manage-billing link) ===== -->
		<section class="jv-acct-card">
			<div v-if="accountLoading" class="jv-acct-muted">Loading…</div>
			<div v-else-if="accountErr" class="jv-acct-err">
				{{ accountErr }}
				<button type="button" class="jv-mon-retry" @click="loadAccount">Retry</button>
			</div>
			<template v-else>
				<div v-if="!account.plan || !account.plan.plan_name" class="jv-acct-muted">No active plan yet.</div>
				<template v-else>
					<!-- current plan: name · price · status badge on one line -->
					<div class="jv-acct-plan-row">
						<div class="jv-acct-plan-name">{{ account.plan.plan_name }}</div>
						<div class="jv-acct-plan-price">{{ planPriceLabel(account.plan.price_inr, account.plan.billing_cycle) }}</div>
						<span class="jv-acct-pill" :class="pillTone">{{ statusLabel(account.subscription_status) }}</span>
					</div>
					<div class="jv-acct-renewal">
						{{ renewalLabel(account.current_period_end, account.days_remaining) }}<template v-if="account.autorenew"> · Auto-renew on</template>
					</div>
					<ul v-if="planFeatures.length" class="jv-acct-features">
						<li v-for="(f, i) in planFeatures" :key="i">
							<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
							<span>{{ f }}</span>
						</li>
					</ul>
				</template>

				<!-- Upgrade / Renew — deep-links to the existing Desk billing flow
					 (Razorpay checkout). No new payment logic in this phase; the
					 wizard-driven upgrade UI is a Phase-2 item. -->
				<div v-if="upgradePlans.length" class="jv-acct-upgrades">
					<div class="jv-acct-upgrades-label">Upgrade options</div>
					<div class="jv-acct-upgrade-grid">
						<div v-for="p in upgradePlans" :key="p.name" class="jv-acct-upgrade-card">
							<div class="jv-acct-upgrade-head">
								<div class="jv-acct-upgrade-name">{{ p.plan_name || p.name }}</div>
								<div class="jv-acct-upgrade-price">{{ planPriceLabel(p.price_inr, p.billing_cycle) }}</div>
							</div>
							<div class="jv-acct-upgrade-act">
								<a :href="billingUrl" class="jv-acct-btn-sm">Upgrade</a>
							</div>
						</div>
					</div>
				</div>
				<a :href="billingUrl" class="jv-acct-link">
					Manage plan &amp; billing
					<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><path d="M15 3h6v6" /><path d="M10 14 21 3" /></svg>
				</a>
			</template>
		</section>
	</div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { getAccount } from "@/api"
import { statusLabel, planPriceLabel, renewalLabel } from "@/account/format.js"
import { errMessage as errMsg } from "@/lib/errors"

// The desk page (still Razorpay-backed) is the existing billing entry point.
const billingUrl = "/app/jarvis-account?billing=1"

const account = ref({})
const accountLoading = ref(true)
const accountErr = ref("")

const planFeatures = computed(() => {
	const f = account.value.plan && account.value.plan.features
	if (Array.isArray(f)) return f
	if (typeof f === "string" && f.trim()) {
		try {
			const parsed = JSON.parse(f)
			return Array.isArray(parsed) ? parsed : []
		} catch (e) { return [] }
	}
	return []
})
const upgradePlans = computed(() => account.value.upgrade_plans || [])
const pillTone = computed(() => {
	const sub = account.value.subscription_status
	if (sub === "Active") return "jv-pill-ok"
	if (sub === "Cancelled" || sub === "Past Due" || sub === "Pending Payment" || sub === "Pending Verification") return "jv-pill-warn"
	if (sub === "Expired") return "jv-pill-bad"
	return "jv-pill-muted"
})

async function loadAccount() {
	accountLoading.value = true
	accountErr.value = ""
	try { account.value = (await getAccount()) || {} }
	catch (e) { accountErr.value = errMsg(e) }
	finally { accountLoading.value = false }
}

onMounted(loadAccount)
</script>
