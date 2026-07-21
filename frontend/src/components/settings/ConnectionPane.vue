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
			<template v-else>
				<div class="jv-mon-kv">
					<span>Status</span>
					<b :class="statusClass">{{ statusLabel }}</b>
				</div>
				<div v-if="conn.default_model" class="jv-mon-kv">
					<span>Model</span><b>{{ conn.default_model }}</b>
				</div>
				<div v-if="isProxy && conn.oauth_expires_at" class="jv-mon-kv">
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

// get_llm_connection_status now short-circuits server-side for a DIRECT
// (single-model) tenant instead of surfacing the raw proxy-auth payload, so
// `proxy_active` tells the two states apart explicitly - no more guessing
// from which fields happen to be populated (that heuristic used to misread
// a direct tenant's own default_model as "connection details present" and
// render an orange "Not connected" even though chat worked fine).
const isProxy = computed(() => !!conn.value.proxy_active);
const statusLabel = computed(() => {
	if (!isProxy.value) return "Direct";
	return conn.value.auth_present ? "Connected" : "Not connected";
});
// Direct is a mode, not a warning - neutral text, no jv-ok/jv-warn tint
// (matches BillingMeteringPane's uncoloured "Mode" row for the same value).
const statusClass = computed(() => {
	if (!isProxy.value) return "";
	return conn.value.auth_present ? "jv-ok" : "jv-warn";
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
