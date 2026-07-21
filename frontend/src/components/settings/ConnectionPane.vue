<template>
	<div class="jv-settings-body">
		<!-- The dialog header already titles this pane — no duplicate heading here
         (design.md §4.1). -->
		<section class="jv-mon-card">
			<div v-if="!isSystemManager" class="jv-mon-note">
				Connection details are available to System Managers only.
			</div>
			<div v-else-if="loading" class="jv-mon-note">Checking…</div>
			<div v-else-if="err" class="jv-mon-note">
				Connection status is unavailable right now.
				<button type="button" class="jv-mon-retry" @click="load">Retry</button>
			</div>
			<div v-else-if="!applicable" class="jv-mon-note">
				Connection details apply to multi-model (proxy) setups. This tenant runs a single
				model (direct), so there is no proxy connection to report.
			</div>
			<template v-else>
				<div class="jv-mon-kv">
					<span>Status</span>
					<b :class="conn.auth_present ? 'jv-ok' : 'jv-warn'">{{
						conn.auth_present ? "Connected" : "Not connected"
					}}</b>
				</div>
				<div v-if="conn.default_model" class="jv-mon-kv">
					<span>Model</span><b>{{ conn.default_model }}</b>
				</div>
				<div v-if="conn.oauth_expires_at" class="jv-mon-kv">
					<span>Expires</span><b>{{ expiresLabel }}</b>
				</div>
			</template>
		</section>
	</div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { getLlmConnectionStatus } from "@/api";

// Admin-tier endpoint (server enforces `require_jarvis_admin`); the rail already
// gates this pane, but guard the fetch so a non-admin never fires a doomed
// request and sees a clear note instead. PART 4 REVISED TASK 49(c): widened to
// the Jarvis Admin tenant-admin tier.
const isSystemManager = !!(window.is_system_manager || window.is_jarvis_admin);

const conn = ref({});
const loading = ref(true);
const err = ref(false);

// Deduped from AccountView + MonitorTab (the two identical Connection cards):
// oauth_expires_at is an epoch-ms value, rendered in the viewer's locale.
const expiresLabel = computed(() => {
	const ms = conn.value.oauth_expires_at;
	return ms ? new Date(Number(ms)).toLocaleString() : "—";
});

// Connection is only meaningful for proxy tenants. get_llm_connection_status
// returns proxy auth/profile fields; a direct (single-model) tenant has none
// of them, so treat an empty payload as "not applicable" rather than a
// misleading "Not connected".
const applicable = computed(() => {
	const c = conn.value || {};
	return !!(
		c.auth_present ||
		c.default_model ||
		c.oauth_expires_at ||
		(Array.isArray(c.profile_ids) && c.profile_ids.length)
	);
});

async function load() {
	if (!isSystemManager) {
		loading.value = false;
		return;
	}
	loading.value = true;
	err.value = false;
	try {
		conn.value = (await getLlmConnectionStatus()) || {};
	} catch (e) {
		err.value = true;
	} finally {
		loading.value = false;
	}
}

onMounted(load);
</script>
