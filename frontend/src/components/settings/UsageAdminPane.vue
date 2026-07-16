<template>
	<div class="jv-settings-body">
		<div class="jv-usr-head">
			<div class="jv-set-sec" style="margin:0;">Team usage</div>
			<button class="jv-btn jv-btn--sm jv-btn--ghost" :disabled="syncing" @click="onSync">
				<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v6h6M21 12a9 9 0 1 1-3-6.7L21 8" /></svg>
				{{ syncing ? "Syncing…" : "Sync from agent" }}
			</button>
		</div>

		<div v-if="syncReason" class="jv-run-err" style="margin-bottom:12px;">
			<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4M12 17h.01" /></svg>
			{{ syncReason }}
		</div>
		<div v-else-if="syncResult" class="jv-set-hint" style="color:var(--green);margin-bottom:12px;">{{ syncResult }}</div>

		<div v-if="loadError" class="jv-mon-note">
			Could not load usage. <button type="button" class="jv-mon-retry" @click="loadUsers">Retry</button>
		</div>
		<div v-else-if="loading && !users.length" class="jv-mon-note">Loading…</div>
		<div v-else-if="!users.length" class="jv-set-empty" style="text-align:center;padding:30px 0;">No users with settings or usage yet.</div>

		<template v-else>
			<div class="jv-usr-row jv-usr-headrow">
				<div>User</div>
				<div>This month</div>
				<div>Monthly limit</div>
				<div>Last activity</div>
			</div>
			<div v-for="u in users" :key="u.user" class="jv-usr-row">
				<div class="jv-usr-id">
					<div class="jv-usr-name">{{ u.full_name || u.user }}</div>
					<div class="jv-usr-email">{{ u.user }}</div>
				</div>
				<div class="jv-usr-meter">
					<template v-if="u.monthly_token_limit > 0">
						<div class="jv-usage-bar"><div class="jv-usage-fill" :style="{ width: pct(u) + '%' }"></div></div>
						<div class="jv-set-hint">{{ fmtTokens(u.month_tokens) }} / {{ fmtTokens(u.monthly_token_limit) }} · {{ pct(u) }}%</div>
					</template>
					<div v-else class="jv-set-hint">{{ fmtTokens(u.month_tokens) }} this month · unlimited</div>
					<div class="jv-usr-totalhint">{{ fmtTokens(u.total_tokens) }} total</div>
				</div>
				<div class="jv-usr-limit">
					<input
						type="number" min="0" step="1000" class="jv-usr-limitinput"
						v-model.number="u._limitDraft" :disabled="u._saving" placeholder="0 = unlimited"
					/>
					<button
						class="jv-btn jv-btn--sm jv-btn--ghost"
						:disabled="u._saving || Number(u._limitDraft || 0) === Number(u.monthly_token_limit || 0)"
						@click="saveLimit(u)"
					>{{ u._saving ? "…" : "Save" }}</button>
				</div>
				<div class="jv-usr-last">{{ u.last_usage_at ? timeAgo(u.last_usage_at) : "—" }}</div>
			</div>
		</template>
	</div>
</template>

<script setup>
// Tenant-admin usage table (design doc §6, §4 admin_* endpoints). Gated at
// the SettingsDialog level by window.is_jarvis_admin — the server re-checks
// require_jarvis_admin() independently on every call here, so a stale client
// gate can only hide the nav item, never bypass the real permission.
import { ref, onMounted } from "vue"
import { toast } from "frappe-ui"
import { timeAgo } from "@/utils/datetime"
import * as api from "@/api"

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

const users = ref([])
const loading = ref(false)
const loadError = ref(false)

async function loadUsers() {
	loading.value = true
	loadError.value = false
	try {
		const res = await api.adminListUserUsage()
		if (res && res.ok === false) {
			loadError.value = true
			return
		}
		const rows = (res && res.data) || []
		// _limitDraft is the editable copy the number input binds to; kept
		// separate from monthly_token_limit so the Save button can tell when
		// the row is dirty (and revert cleanly if the request fails).
		users.value = rows.map((u) => ({ ...u, _limitDraft: u.monthly_token_limit || 0, _saving: false }))
	} catch (e) {
		loadError.value = true
	} finally {
		loading.value = false
	}
}

function fmtTokens(n) {
	n = Number(n || 0)
	if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M"
	if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k"
	return String(n)
}
function pct(u) {
	if (!u || !u.monthly_token_limit) return 0
	return Math.min(100, Math.round((Number(u.month_tokens || 0) / Number(u.monthly_token_limit)) * 100))
}

async function saveLimit(u) {
	const val = Math.max(0, Math.round(Number(u._limitDraft) || 0))
	u._saving = true
	try {
		const res = await api.adminSetUserLimit(u.user, val)
		if (res && res.ok === false) {
			toast.error(res.reason || "Could not update the limit.")
			return
		}
		const d = (res && res.data) || {}
		u.monthly_token_limit = d.monthly_token_limit != null ? d.monthly_token_limit : val
		u._limitDraft = u.monthly_token_limit
		toast.success("Limit updated")
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		u._saving = false
	}
}

// "Sync from agent" — sweeps the openclaw gateway's sessions.list to refresh
// per-session snapshots, then reloads the table. admin_sync_usage can return
// {ok:false, reason:"gateway_unreachable"} (agent container down/unpaired) —
// surfaced verbatim rather than a generic error, since it's actionable.
const syncing = ref(false)
const syncReason = ref("")
const syncResult = ref("")
async function onSync() {
	syncing.value = true
	syncReason.value = ""
	syncResult.value = ""
	try {
		const res = await api.adminSyncUsage()
		if (res && res.ok === false) {
			syncReason.value = res.reason || "Sync failed."
			return
		}
		const d = (res && res.data) || {}
		syncResult.value = `Synced ${d.synced_sessions ?? 0} session${d.synced_sessions === 1 ? "" : "s"} · ${d.users_updated ?? 0} user${d.users_updated === 1 ? "" : "s"} updated`
		await loadUsers()
	} catch (e) {
		syncReason.value = errMsg(e)
	} finally {
		syncing.value = false
	}
}

onMounted(loadUsers)
</script>

<style scoped>
.jv-usr-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 14px; }
.jv-usr-row { display: grid; grid-template-columns: 1.5fr 1.8fr 1.3fr 0.9fr; gap: 14px; align-items: center; padding: 12px 0; border-bottom: 1px solid var(--border); }
.jv-usr-row:last-child { border-bottom: 0; }
.jv-usr-headrow { padding-top: 0; padding-bottom: 8px; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); }
.jv-usr-id { display: flex; flex-direction: column; gap: 2px; }
.jv-usr-name { font-size: 13.5px; font-weight: 600; color: var(--text); }
.jv-usr-email { font-size: 11.5px; color: var(--text-3); margin-top: 1px; }
.jv-usr-meter .jv-usage-bar { margin-top: 0; }
.jv-usr-totalhint { font-size: 11px; color: var(--text-3); margin-top: 4px; }
.jv-usr-limit { display: flex; align-items: center; gap: 6px; }
.jv-usr-limitinput { width: 74px; flex: none; padding: 6px 8px; font-size: 12.5px; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); color: var(--text); font-family: inherit; box-sizing: border-box; }
.jv-usr-limitinput:focus { outline: none; border-color: var(--cta-bd); }
.jv-usr-limitinput::-webkit-outer-spin-button, .jv-usr-limitinput::-webkit-inner-spin-button { margin: 0; }
.jv-usr-last { font-size: 12px; color: var(--text-3); text-align: right; }
</style>
