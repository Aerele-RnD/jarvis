<template>
  <div class="jv-settings-body">
    <div class="jv-mon">
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
        <div v-if="usageError" class="jv-mon-note">
          Usage is unavailable right now. <button type="button" class="jv-mon-retry" @click="loadAll">Retry</button>
        </div>
        <div v-else-if="!usage.applicable" class="jv-mon-note">
          Usage is available on multi-model (proxy) setups. This tenant runs a single model (direct), so there is no proxy to meter.
        </div>
        <template v-else>
          <div class="jv-statgrid jv-mon-statgrid">
            <div class="jv-stat">
              <div class="jv-stat-label">Tokens in</div>
              <div class="jv-stat-val">{{ usage.tokens_in }}</div>
            </div>
            <div class="jv-stat">
              <div class="jv-stat-label">Tokens out</div>
              <div class="jv-stat-val">{{ usage.tokens_out }}</div>
            </div>
            <div class="jv-stat">
              <div class="jv-stat-label">Cost</div>
              <div class="jv-stat-val">${{ usage.cost_usd }}</div>
            </div>
          </div>
          <JvChart v-if="perModelSpec" :spec="perModelSpec" :dark="dark" />
          <EChart v-if="gaugeOption" :option="gaugeOption" />
        </template>
      </section>

      <!-- "Request log & failover history" placeholder removed — no "coming
           soon" cards in the language (design.md §5 #18); the section returns
           when the feature ships. -->
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import JvChart from "@/charts/JvChart.vue"
import EChart from "@/charts/EChart.vue"
import { budgetGaugeOption, perModelBarSpec } from "@/charts/usageCharts.js"
import { getLlmConfig, getLlmUsage, getLlmSyncStatus } from "@/api"
import { useJarvisTheme } from "@/theme"

const { effectiveDark: dark } = useJarvisTheme()

const config = ref({ models: [], proxy_active: 0 })
const usage = ref({ applicable: false, per_model: [], used_vs_limit: {} })
const sync = ref({})
const usageError = ref(false)

const perModelSpec = computed(() =>
  (usage.value.per_model || []).length ? perModelBarSpec(usage.value.per_model, "tokens") : null)
const gaugeOption = computed(() => {
  const uv = usage.value.used_vs_limit || {}
  return budgetGaugeOption(uv.used_usd, uv.limit_usd, dark.value)
})

async function load(fetchFn, target) {
  try { target.value = (await fetchFn()) || target.value; return true }
  catch (e) { return false }
}
async function loadAll() {
  usageError.value = false
  // Order matters: results map 1:1 to the calls below. A failed usage fetch must
  // set usageError so the card shows "unavailable · retry" instead of the false
  // "single model (direct)" note a transient error would otherwise render.
  const [, usageOk] = await Promise.all([
    load(getLlmConfig, config), load(getLlmUsage, usage), load(getLlmSyncStatus, sync),
  ])
  if (!usageOk) usageError.value = true
}
onMounted(loadAll)
</script>

<style scoped>
.jv-mon-statgrid { grid-template-columns: repeat(3, 1fr); margin-bottom: 12px; }
</style>
