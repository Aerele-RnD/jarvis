<template>
  <div class="jv-mon">
    <div v-if="denied" class="jv-mon-empty">This view is available to System Managers only.</div>
    <template v-else>
      <section class="jv-mon-card">
        <h3>Status</h3>
        <div class="jv-mon-kv"><span>Mode</span><b>{{ config.proxy_active ? "Proxy" : "Direct" }}</b></div>
        <div class="jv-mon-kv"><span>Sync</span><b>{{ sync.last_sync_status || "—" }}</b></div>
        <div v-if="sync.last_sync_at" class="jv-mon-kv"><span>Last sync</span><b>{{ sync.last_sync_at }}</b></div>
      </section>

      <section class="jv-mon-card">
        <h3>Active pool</h3>
        <div class="jv-mon-kv"><span>Preset</span><b>{{ config.preset || "Custom" }}</b></div>
        <div class="jv-mon-kv"><span>Routing</span><b>{{ config.routing_mode || "failover" }}</b></div>
        <ol class="jv-mon-models">
          <li v-for="(m, i) in (config.models || [])" :key="i">
            {{ m.provider }} · {{ m.model }}
            <span class="jv-mon-tag">{{ i === 0 ? "runs every turn" : "backup" }}</span>
          </li>
        </ol>
      </section>

      <section class="jv-mon-card">
        <h3>Usage <span class="jv-mon-sub">· {{ usage.period || "current period" }}</span></h3>
        <div v-if="!usage.applicable" class="jv-mon-note">
          Usage is available on multi-model (proxy) setups. This tenant runs a single model (direct), so there is no proxy to meter.
        </div>
        <template v-else>
          <div class="jv-mon-stats">
            <div><span>Tokens in</span><b>{{ usage.tokens_in }}</b></div>
            <div><span>Tokens out</span><b>{{ usage.tokens_out }}</b></div>
            <div><span>Cost</span><b>${{ usage.cost_usd }}</b></div>
          </div>
          <JvChart v-if="perModelSpec" :spec="perModelSpec" :dark="dark" />
          <EChart v-if="gaugeOption" :option="gaugeOption" />
        </template>
      </section>

      <section class="jv-mon-card">
        <h3>Connection</h3>
        <div class="jv-mon-kv"><span>Auth</span><b>{{ conn.auth_present ? "Connected" : "Not connected" }}</b></div>
        <div v-if="conn.oauth_expires_at" class="jv-mon-kv"><span>Expires</span><b>{{ expiresLabel }}</b></div>
      </section>

      <section class="jv-mon-card jv-mon-soon">
        <h3>Request log &amp; failover history</h3>
        <div class="jv-mon-note">Coming soon.</div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import JvChart from "@/charts/JvChart.vue"
import EChart from "@/charts/EChart.vue"
import { budgetGaugeOption, perModelBarSpec } from "@/charts/usageCharts.js"
import { getLlmConfig, getLlmUsage, getLlmConnectionStatus, getLlmSyncStatus } from "@/api"

const props = defineProps({ dark: { type: Boolean, default: false } })
const config = ref({ models: [], proxy_active: 0 })
const usage = ref({ applicable: false, per_model: [], used_vs_limit: {} })
const conn = ref({})
const sync = ref({})
const denied = ref(false)

const perModelSpec = computed(() =>
  (usage.value.per_model || []).length ? perModelBarSpec(usage.value.per_model, "tokens") : null)
const gaugeOption = computed(() => {
  const uv = usage.value.used_vs_limit || {}
  return budgetGaugeOption(uv.used_usd, uv.limit_usd, props.dark)
})
const expiresLabel = computed(() => {
  const ms = conn.value.oauth_expires_at
  return ms ? new Date(Number(ms)).toLocaleString() : "—"
})

async function load(fetchFn, target) {
  try { target.value = (await fetchFn()) || target.value }
  catch (e) { if (String(e && e.message).includes("PermissionError")) denied.value = true }
}
onMounted(async () => {
  await Promise.all([
    load(getLlmConfig, config), load(getLlmUsage, usage),
    load(getLlmConnectionStatus, conn), load(getLlmSyncStatus, sync),
  ])
})
</script>

<style scoped>
.jv-mon { display: grid; gap: 14px; }
.jv-mon-card { border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; background: var(--surface); }
.jv-mon-card h3 { font-size: 14px; font-weight: 600; margin: 0 0 10px; }
.jv-mon-sub, .jv-mon-tag { color: var(--text-3); font-weight: 450; font-size: 12px; }
.jv-mon-kv { display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; }
.jv-mon-models { margin: 6px 0 0; padding-left: 18px; font-size: 13px; }
.jv-mon-stats { display: flex; gap: 20px; margin-bottom: 10px; font-size: 13px; }
.jv-mon-note, .jv-mon-empty { font-size: 13px; color: var(--text-3); }
.jv-mon-empty { padding: 40px; text-align: center; }
</style>
