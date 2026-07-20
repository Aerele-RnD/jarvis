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
				<div v-if="!account.plan || !account.plan.plan_name" class="jv-acct-muted">
					No active plan yet.
				</div>
				<template v-else>
					<!-- current plan: name · price · status badge on one line -->
					<div class="jv-acct-plan-row">
						<div class="jv-acct-plan-name">{{ account.plan.plan_name }}</div>
						<div class="jv-acct-plan-price">
							{{
								planPriceLabel(account.plan.price_inr, account.plan.billing_cycle)
							}}
						</div>
						<span class="jv-acct-pill" :class="tone">{{
							statusLabel(account.subscription_status, cancelling)
						}}</span>
					</div>
					<div class="jv-acct-renewal">
						{{ renewalLabel(account.current_period_end, account.days_remaining)
						}}<template v-if="account.autorenew && !cancelling">
							· Auto-renew on</template
						>
					</div>
					<!-- A scheduled cancellation must be visible on sight: it is the
						 only affordance that surfaces Resume, and an invisible one
						 generates support tickets. -->
					<div v-if="cancelling" class="jv-acct-notice">
						{{ cancellationNotice(account.access_ends_on) }}
					</div>
					<ul v-if="planFeatures.length" class="jv-acct-features">
						<li v-for="(f, i) in planFeatures" :key="i">
							<svg
								width="14"
								height="14"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M20 6 9 17l-5-5" />
							</svg>
							<span>{{ f }}</span>
						</li>
					</ul>
				</template>

				<!-- Upgrade / Renew — deep-links to the existing Desk billing flow
					 (Razorpay checkout). No new payment logic in this phase; the
					 wizard-driven upgrade UI is a Phase-2 item. -->
				<!-- Hidden while cancelling: the server refuses upgrades with
					 ResumeBeforeUpgrade, and offering a CTA that 400s is worse
					 than offering none. -->
				<div v-if="upgradePlans.length && !cancelling" class="jv-acct-upgrades">
					<div class="jv-acct-upgrades-label">Upgrade options</div>
					<div class="jv-acct-upgrade-grid">
						<div v-for="p in upgradePlans" :key="p.name" class="jv-acct-upgrade-card">
							<div class="jv-acct-upgrade-head">
								<div class="jv-acct-upgrade-name">{{ p.plan_name || p.name }}</div>
								<div class="jv-acct-upgrade-price">
									{{ planPriceLabel(p.price_inr, p.billing_cycle) }}
								</div>
							</div>
							<div class="jv-acct-upgrade-act">
								<a :href="billingUrl" class="jv-acct-btn-sm">Upgrade</a>
							</div>
						</div>
					</div>
				</div>
				<div v-if="account.plan && account.plan.plan_name" class="jv-acct-actions">
					<button
						v-if="cancelling"
						type="button"
						class="jv-acct-btn-sm"
						:disabled="busy"
						@click="doResume"
					>
						Resume subscription
					</button>
					<button
						v-else
						type="button"
						class="jv-btn jv-btn--danger"
						:disabled="busy"
						@click="doCancel"
					>
						{{ cancelActionLabel(account.has_mandate) }}
					</button>
				</div>
				<div v-if="reauthNotice" class="jv-acct-notice">{{ reauthNotice }}</div>

				<a :href="billingUrl" class="jv-acct-link">
					Manage plan &amp; billing
					<svg
						width="13"
						height="13"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.5"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
						<path d="M15 3h6v6" />
						<path d="M10 14 21 3" />
					</svg>
				</a>
			</template>
		</section>
	</div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { getAccount, cancelPlanAtPeriodEnd, resumePlan } from "@/api";
import {
	statusLabel,
	pillTone,
	planPriceLabel,
	renewalLabel,
	cancelActionLabel,
	cancellationNotice,
} from "@/account/format.js";
import { useConfirm } from "@/composables/useConfirm";
import { errMessage as errMsg } from "@/lib/errors";

const { confirm } = useConfirm();

// The desk page (still Razorpay-backed) is the existing billing entry point.
const billingUrl = "/app/jarvis-account?billing=1";

const account = ref({});
const accountLoading = ref(true);
const accountErr = ref("");

const planFeatures = computed(() => {
	const f = account.value.plan && account.value.plan.features;
	if (Array.isArray(f)) return f;
	if (typeof f === "string" && f.trim()) {
		try {
			const parsed = JSON.parse(f);
			return Array.isArray(parsed) ? parsed : [];
		} catch (e) {
			return [];
		}
	}
	return [];
});
const upgradePlans = computed(() => account.value.upgrade_plans || []);
// A plan scheduled to end. Server keeps status "Active" through the paid
// period, so this flag - not the status - drives the cancelling UI.
const cancelling = computed(() => !!account.value.cancel_at_period_end);
const tone = computed(() =>
	pillTone(account.value.subscription_status, cancelling.value),
);
const busy = ref(false);
const reauthNotice = ref("");

async function loadAccount() {
	accountLoading.value = true;
	accountErr.value = "";
	try {
		account.value = (await getAccount()) || {};
	} catch (e) {
		accountErr.value = errMsg(e);
	} finally {
		accountLoading.value = false;
	}
}

async function doCancel() {
	const label = cancelActionLabel(account.value.has_mandate);
	const endsOn = (account.value.access_ends_on || "").split(" ")[0];
	const ok = await confirm({
		title: `${label}?`,
		message: endsOn
			? `You'll keep full access until ${endsOn}. You can resume any time before then.`
			: "You'll keep full access until the end of your current period, and can resume any time before then.",
		confirmLabel: label,
		danger: true,
	});
	if (!ok) return;
	busy.value = true;
	accountErr.value = "";
	reauthNotice.value = "";
	try {
		await cancelPlanAtPeriodEnd();
		// Re-read rather than optimistically patching: the server payload is
		// the truth, and it is a single round-trip.
		await loadAccount();
	} catch (e) {
		accountErr.value = errMsg(e);
	} finally {
		busy.value = false;
	}
}

async function doResume() {
	// Constructive action - no danger confirm.
	busy.value = true;
	accountErr.value = "";
	try {
		const out = (await resumePlan()) || {};
		if (out.requires_reauthorization) {
			// Cancelling released the autopay mandate and there is no way to
			// re-arm it silently; say so rather than let them assume it renews.
			const endsOn = (account.value.access_ends_on || "").split(" ")[0];
			reauthNotice.value = endsOn
				? `Auto-renewal is off. Set up payment again before ${endsOn} to stay subscribed.`
				: "Auto-renewal is off. Set up payment again before your period ends.";
		}
		await loadAccount();
	} catch (e) {
		accountErr.value = errMsg(e);
	} finally {
		busy.value = false;
	}
}

onMounted(loadAccount);
</script>
