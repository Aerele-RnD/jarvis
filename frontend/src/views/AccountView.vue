<template>
	<div class="jv-root" :class="{ 'jv-dark': dark }" :style="paletteVars"
		 style="--rad:8px;font-family:'Inter',system-ui,sans-serif;min-height:100vh;color:var(--text);background:var(--surface);">

		<!-- Header -->
		<header class="jv-acct-head">
			<router-link to="/" class="jv-acct-back">← Chat</router-link>
			<span class="jv-acct-title">Account</span>
			<button @click="toggleTheme" :title="dark ? 'Switch to light theme' : 'Switch to dark theme'" class="jv-acct-themebtn">
				<svg v-if="dark" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
				<svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
			</button>
		</header>

		<main class="jv-acct-wrap">
			<!-- ===== Plan & billing ===== -->
			<section class="jv-acct-card">
				<div class="jv-acct-card-head">
					<h2>Plan &amp; billing</h2>
					<span v-if="account.plan && account.plan.plan_name" class="jv-acct-pill" :class="pillTone">{{ statusLabel(account.subscription_status) }}</span>
				</div>

				<div v-if="accountLoading" class="jv-acct-muted">Loading…</div>
				<div v-else-if="accountErr" class="jv-acct-err">{{ accountErr }}</div>
				<template v-else>
					<div v-if="!account.plan || !account.plan.plan_name" class="jv-acct-muted">No active plan yet.</div>
					<template v-else>
						<div class="jv-acct-plan-row">
							<div class="jv-acct-plan-name">{{ account.plan.plan_name }}</div>
							<div class="jv-acct-plan-price">{{ planPriceLabel(account.plan.price_inr, account.plan.billing_cycle) }}</div>
						</div>
						<div class="jv-acct-renewal">
							{{ renewalLabel(account.current_period_end, account.days_remaining) }}<template v-if="account.autorenew"> · Auto-renew on</template>
						</div>
						<ul v-if="planFeatures.length" class="jv-acct-features">
							<li v-for="(f, i) in planFeatures" :key="i">{{ f }}</li>
						</ul>
					</template>

					<!-- Upgrade / Renew — deep-links to the existing Desk billing flow
						 (Razorpay checkout). No new payment logic in this phase; the
						 wizard-driven upgrade UI is a Phase-2 item. -->
					<div v-if="upgradePlans.length" class="jv-acct-upgrades">
						<div class="jv-acct-upgrades-label">Upgrade options</div>
						<div class="jv-acct-upgrade-grid">
							<div v-for="p in upgradePlans" :key="p.name" class="jv-acct-upgrade-card">
								<div class="jv-acct-upgrade-name">{{ p.plan_name || p.name }}</div>
								<div class="jv-acct-upgrade-price">{{ planPriceLabel(p.price_inr, p.billing_cycle) }}</div>
								<a :href="billingUrl" class="jv-acct-btn-sm">Upgrade →</a>
							</div>
						</div>
					</div>
					<a :href="billingUrl" class="jv-acct-link">Manage billing &amp; payment history (opens Desk) →</a>
				</template>
			</section>

			<!-- ===== AI models ===== -->
			<section class="jv-acct-card">
				<div class="jv-acct-card-head">
					<h2>AI models</h2>
					<span v-if="savedNote" class="jv-acct-savednote">{{ savedNote }}</span>
				</div>
				<LlmPoolEditor :editable="isSystemManager" @saved="onSaved" />
			</section>

			<!-- ===== Connection ===== -->
			<section class="jv-acct-card">
				<h2>Connection</h2>
				<div v-if="connLoading" class="jv-acct-muted">Checking…</div>
				<div v-else-if="connErr" class="jv-acct-err">{{ connErr }}</div>
				<template v-else>
					<div class="jv-acct-kv"><span>Status</span><b :class="conn.auth_present ? 'jv-ok' : 'jv-warn'">{{ conn.auth_present ? "Connected" : "Not connected" }}</b></div>
					<div v-if="conn.default_model" class="jv-acct-kv"><span>Model</span><b>{{ conn.default_model }}</b></div>
					<div v-if="conn.oauth_expires_at" class="jv-acct-kv"><span>Expires</span><b>{{ expiresLabel }}</b></div>
				</template>
			</section>

			<!-- ===== Usage (compact — full dashboard lives on the Monitor tab) ===== -->
			<section class="jv-acct-card">
				<h2>Usage<span v-if="usage.period" class="jv-acct-sub"> · {{ usage.period }}</span></h2>
				<div v-if="usageLoading" class="jv-acct-muted">Loading…</div>
				<div v-else-if="usageErr" class="jv-acct-err">{{ usageErr }}</div>
				<div v-else-if="!usage.applicable" class="jv-acct-muted">Usage metering applies to multi-model (proxy) setups.</div>
				<div v-else class="jv-acct-usage-line">{{ usage.tokens_in || 0 }} tokens in · {{ usage.tokens_out || 0 }} tokens out · ${{ costLabel }}</div>
			</section>
		</main>
	</div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import { useTheme } from "@/composables/useTheme"
import { getAccount, getLlmConnectionStatus, getLlmUsage } from "@/api"
import { statusLabel, planPriceLabel, renewalLabel } from "@/account/format.js"
import LlmPoolEditor from "@/components/LlmPoolEditor.vue"

// Theme — shared composable: honours "jarvis-theme" pref, cross-tab sync, OS live.
const { effectiveDark: dark, paletteVars, toggleTheme } = useTheme()

// Route-level guard already restricts /account to System Managers; this flag
// additionally gates the editor's edit affordances + which sections fetch.
const isSystemManager = !!window.is_system_manager

// The desk page (still Razorpay-backed) is the existing billing entry point.
// Building a new payment flow here is explicitly out of scope for this phase.
const billingUrl = "/app/jarvis-account"

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

// ---- Plan & billing --------------------------------------------------------
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

// ---- AI models: brief save acknowledgement (editor persists itself) -------
const savedNote = ref("")
let savedTimer = null
function onSaved(sync) {
	savedNote.value = sync && sync.pending ? "Saved — syncing…" : "Saved"
	clearTimeout(savedTimer)
	savedTimer = setTimeout(() => { savedNote.value = "" }, 4000)
}

// ---- Connection -------------------------------------------------------------
const conn = ref({})
const connLoading = ref(true)
const connErr = ref("")
const expiresLabel = computed(() => {
	const ms = conn.value.oauth_expires_at
	return ms ? new Date(Number(ms)).toLocaleString() : "—"
})
async function loadConnection() {
	if (!isSystemManager) { connLoading.value = false; return }
	connLoading.value = true
	connErr.value = ""
	try { conn.value = (await getLlmConnectionStatus()) || {} }
	catch (e) { connErr.value = errMsg(e) }
	finally { connLoading.value = false }
}

// ---- Usage (compact) --------------------------------------------------------
const usage = ref({ applicable: false })
const usageLoading = ref(true)
const usageErr = ref("")
const costLabel = computed(() => Number(usage.value.cost_usd || 0).toFixed(2))
async function loadUsage() {
	if (!isSystemManager) { usageLoading.value = false; return }
	usageLoading.value = true
	usageErr.value = ""
	try { usage.value = (await getLlmUsage()) || { applicable: false } }
	catch (e) { usageErr.value = errMsg(e) }
	finally { usageLoading.value = false }
}

onMounted(() => {
	loadAccount()
	loadConnection()
	loadUsage()
})
</script>

<style scoped>
.jv-acct-head {
	height: 52px;
	display: flex;
	align-items: center;
	gap: 14px;
	padding: 0 18px;
	border-bottom: 1px solid var(--border);
}
.jv-acct-back { color: var(--text-2); text-decoration: none; font-size: 13px; flex: none; }
.jv-acct-title { font-size: 14px; font-weight: 600; }
.jv-acct-themebtn {
	margin-left: auto;
	width: 32px; height: 32px; flex: none;
	display: flex; align-items: center; justify-content: center;
	background: var(--surface); border: 1px solid var(--border); border-radius: 7px; cursor: pointer;
}
.jv-acct-wrap {
	max-width: 720px;
	margin: 0 auto;
	padding: 22px 18px 60px;
	display: flex;
	flex-direction: column;
	gap: 16px;
}
.jv-acct-card {
	border: 1px solid var(--border);
	border-radius: 12px;
	padding: 16px 18px;
	background: var(--surface);
}
.jv-acct-card h2 { font-size: 14px; font-weight: 600; margin: 0 0 10px; }
.jv-acct-card-head {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 10px;
	flex-wrap: wrap;
	margin-bottom: 4px;
}
.jv-acct-card-head h2 { margin-bottom: 0; }
.jv-acct-sub { color: var(--text-3); font-weight: 450; font-size: 12px; }
.jv-acct-muted, .jv-acct-err { font-size: 13px; color: var(--text-3); }
.jv-acct-err { color: var(--red); }
.jv-acct-pill {
	font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; flex: none;
}
.jv-pill-ok { color: var(--green); background: var(--green-bg); }
.jv-pill-warn { color: var(--amber); background: var(--amber-bg); }
.jv-pill-bad { color: var(--red); background: var(--red-bg); }
.jv-pill-muted { color: var(--text-3); background: var(--surface-2); }
.jv-acct-plan-row { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-top: 6px; }
.jv-acct-plan-name { font-size: 18px; font-weight: 600; }
.jv-acct-plan-price { font-size: 13px; color: var(--text-2); }
.jv-acct-renewal { font-size: 12.5px; color: var(--text-3); margin-top: 4px; }
.jv-acct-features { margin: 10px 0 0; padding-left: 18px; font-size: 13px; color: var(--text-2); }
.jv-acct-upgrades { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); }
.jv-acct-upgrades-label { font-size: 11px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .03em; margin-bottom: 8px; }
.jv-acct-upgrade-grid { display: flex; flex-wrap: wrap; gap: 10px; }
.jv-acct-upgrade-card {
	flex: 1 1 160px;
	border: 1px solid var(--border);
	border-radius: 9px;
	padding: 10px 12px;
	background: var(--surface-1);
}
.jv-acct-upgrade-name { font-size: 13px; font-weight: 600; }
.jv-acct-upgrade-price { font-size: 12px; color: var(--text-3); margin: 2px 0 8px; }
.jv-acct-btn-sm {
	display: inline-block; font-size: 12px; font-weight: 600; color: var(--blue);
	text-decoration: none; padding: 5px 10px; border: 1px solid var(--blue-bd); border-radius: 6px; background: var(--blue-bg);
}
.jv-acct-link { display: inline-block; margin-top: 14px; font-size: 12.5px; color: var(--blue); text-decoration: none; }
.jv-acct-savednote { font-size: 12px; color: var(--green); font-weight: 500; }
.jv-acct-kv { display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; gap: 12px; }
.jv-acct-kv .jv-ok { color: var(--green); }
.jv-acct-kv .jv-warn { color: var(--amber); }
.jv-acct-usage-line { font-size: 13px; color: var(--text-2); }

@media (max-width: 520px) {
	.jv-acct-wrap { padding: 16px 12px 48px; }
	.jv-acct-card { padding: 14px; }
}
</style>
