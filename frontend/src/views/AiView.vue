<template>
  <div class="jv-root" :class="{ 'jv-dark': dark }" :style="paletteVars"
       style="--rad:8px;font-family:'Inter',system-ui,sans-serif;min-height:100vh;color:var(--text);background:var(--surface);">

    <!-- Header with tab strip and mode badge -->
    <header style="height:52px;display:flex;align-items:center;gap:14px;padding:0 18px;border-bottom:1px solid var(--border);">
      <router-link to="/" style="color:var(--text-2);text-decoration:none;font-size:13px;">← Chat</router-link>
      <span style="font-size:14px;font-weight:600;">AI / Models</span>
      <nav style="margin-left:12px;display:flex;gap:4px;">
        <button v-for="t in ['manage','monitor']" :key="t" @click="activeTab=t"
          :style="{fontSize:'13px',padding:'6px 12px',border:'none',cursor:'pointer',background:'transparent',
                   borderBottom: activeTab===t ? '2px solid var(--blue)' : '2px solid transparent',
                   color: activeTab===t ? 'var(--text)' : 'var(--text-3)'}">{{ t[0].toUpperCase()+t.slice(1) }}</button>
      </nav>
      <span :style="{marginLeft:'auto',fontSize:'11px',fontWeight:600,padding:'3px 9px',borderRadius:'20px',
             background: mode==='proxy' ? 'var(--green-bg,#e6f4ea)' : 'var(--surface-2,#f4f4f5)',
             color: mode==='proxy' ? 'var(--green)' : 'var(--text-3)'}">
        {{ mode === 'proxy' ? 'Proxy' : 'Direct' }}<template v-if="cfg.proxy_active"> · active</template>
      </span>
    </header>

    <!-- Manage tab -->
    <main v-show="activeTab==='manage'" style="max-width:760px;margin:0 auto;padding:22px 18px;">
      <div v-if="err" style="color:var(--red);font-size:13px;margin-bottom:12px;">{{ err }}</div>

      <!-- Current pool: ordered list of active models -->
      <section style="background:var(--surface-1,#fafafa);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:18px;">
        <div style="font-size:12px;color:var(--text-3);margin-bottom:8px;">
          {{ cfg.preset ? presetLabel(cfg.preset) : 'Custom pool' }} · failover
        </div>
        <div v-if="!models.length" style="font-size:13px;color:var(--text-3);padding:8px 0;">No models configured yet.</div>
        <div v-for="(m,i) in models" :key="i"
             style="display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--border);">
          <span style="font-size:13px;font-weight:550;">{{ m.provider }} / {{ m.model }}</span>
          <span style="font-size:11px;color:var(--text-3);">{{ i === 0 ? 'runs every turn' : 'backup' }}</span>
          <div style="margin-left:auto;display:flex;gap:6px;">
            <button @click="move(i,-1)" :disabled="i===0" title="Up"
                    style="border:1px solid var(--border);background:var(--surface);border-radius:5px;width:24px;height:24px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:11px;"
                    :style="{opacity: i===0 ? '0.35' : '1'}">▲</button>
            <button @click="move(i,1)" :disabled="i===models.length-1" title="Down"
                    style="border:1px solid var(--border);background:var(--surface);border-radius:5px;width:24px;height:24px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:11px;"
                    :style="{opacity: i===models.length-1 ? '0.35' : '1'}">▼</button>
            <button @click="remove(i)" title="Remove"
                    style="border:1px solid var(--red-bd,#f5d4d1);background:var(--red-bg,#fdf0ef);color:var(--red);border-radius:5px;width:24px;height:24px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:11px;">✕</button>
          </div>
        </div>
      </section>

      <!-- Preset picker: cards grouped by kind -->
      <section style="margin-bottom:18px;" v-if="catalog.length">
        <div style="font-size:12px;font-weight:600;color:var(--text-2);margin-bottom:8px;letter-spacing:.03em;text-transform:uppercase;">Presets</div>
        <!-- single_vendor presets -->
        <div v-if="singleVendorPresets.length" style="margin-bottom:10px;">
          <div style="font-size:11px;color:var(--text-3);margin-bottom:6px;">Single-vendor resilience</div>
          <div style="display:flex;flex-wrap:wrap;gap:8px;">
            <button v-for="entry in singleVendorPresets" :key="entry.key"
                    @click="selectPreset(entry)"
                    :style="{
                      padding:'8px 12px',fontSize:'12.5px',cursor:'pointer',borderRadius:'8px',
                      border: selectedPreset===entry.key ? '2px solid var(--blue)' : '1px solid var(--border)',
                      background: selectedPreset===entry.key ? 'var(--blue-bg,#eff4ff)' : 'var(--surface)',
                      color: selectedPreset===entry.key ? 'var(--blue)' : 'var(--text)',
                      opacity: entry.enabled===false ? '0.45' : '1',
                      fontWeight: selectedPreset===entry.key ? '600' : '400'
                    }">
              <div style="font-weight:inherit;">{{ entry.label }}</div>
              <div style="font-size:10.5px;color:var(--text-3);margin-top:2px;">{{ entry.blurb }}</div>
            </button>
          </div>
        </div>
        <!-- cross_vendor presets -->
        <div v-if="crossVendorPresets.length">
          <div style="font-size:11px;color:var(--text-3);margin-bottom:6px;">Cross-vendor strategies</div>
          <div style="display:flex;flex-wrap:wrap;gap:8px;">
            <button v-for="entry in crossVendorPresets" :key="entry.key"
                    @click="selectPreset(entry)"
                    :style="{
                      padding:'8px 12px',fontSize:'12.5px',cursor:'pointer',borderRadius:'8px',
                      border: selectedPreset===entry.key ? '2px solid var(--blue)' : '1px solid var(--border)',
                      background: selectedPreset===entry.key ? 'var(--blue-bg,#eff4ff)' : 'var(--surface)',
                      color: selectedPreset===entry.key ? 'var(--blue)' : 'var(--text)',
                      opacity: entry.enabled===false ? '0.45' : '1',
                      fontWeight: selectedPreset===entry.key ? '600' : '400'
                    }">
              <div style="font-weight:inherit;">{{ entry.label }}</div>
              <div style="font-size:10.5px;color:var(--text-3);margin-top:2px;">{{ entry.blurb }}</div>
            </button>
          </div>
        </div>

        <!-- Progressive vendor key fields for the chosen preset (all-or-nothing) -->
        <div v-if="selectedPreset && missingVendors.length > 0"
             style="margin-top:12px;padding:12px;background:var(--amber-bg,#fdf6ec);border:1px solid var(--amber-bd,#f3e2c2);border-radius:8px;">
          <div style="font-size:12px;color:var(--amber,#d97706);font-weight:600;margin-bottom:8px;">
            Provide API keys for this preset:
          </div>
          <div v-for="vendor in vendorsForPreset" :key="vendor" style="margin-bottom:8px;">
            <label :style="{fontSize:'12px',color:'var(--text-2)',display:'block',marginBottom:'3px'}">
              {{ vendor }} API key<span v-if="missingVendors.includes(vendor)" style="color:var(--red)"> *</span>
            </label>
            <input
              :value="keysByVendor[vendor] || ''"
              @input="keysByVendor[vendor] = $event.target.value"
              type="password"
              :placeholder="vendor + ' API key'"
              style="width:100%;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;box-sizing:border-box;" />
          </div>
        </div>

        <!-- Custom / clear preset: link to remove preset selection -->
        <button v-if="selectedPreset" @click="clearPreset"
                style="margin-top:8px;font-size:12px;color:var(--text-3);background:transparent;border:none;cursor:pointer;padding:4px 0;text-decoration:underline;">
          Switch to Custom (no preset)
        </button>
      </section>

      <!-- Custom "+ Add model" row for Quick/Custom mode — binds to models directly -->
      <section v-if="!selectedPreset" style="margin-bottom:18px;">
        <div style="font-size:12px;font-weight:600;color:var(--text-2);margin-bottom:8px;letter-spacing:.03em;text-transform:uppercase;">Custom models</div>
        <div v-for="(m, i) in models" :key="i"
             style="display:flex;gap:8px;margin-bottom:8px;align-items:center;">
          <input v-model="m.provider" placeholder="Provider (e.g. openai)"
                 style="flex:1;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
          <input v-model="m.model" placeholder="Model ID (e.g. gpt-4o)"
                 style="flex:1.5;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
          <input v-model="m.api_key" :placeholder="m.has_key ? 'key set — re-enter to change' : 'API key'" type="password"
                 style="flex:1.5;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
          <button @click="remove(i)"
                  style="border:1px solid var(--red-bd,#f5d4d1);background:var(--red-bg,#fdf0ef);color:var(--red);border-radius:5px;width:28px;height:28px;cursor:pointer;flex:none;">✕</button>
        </div>
        <button @click="addModel"
                style="font-size:12.5px;color:var(--blue);background:transparent;border:1px dashed var(--border-2);border-radius:7px;padding:6px 14px;cursor:pointer;width:100%;">
          + Add model
        </button>
      </section>

      <!-- Save bar -->
      <div style="display:flex;align-items:center;gap:12px;">
        <button @click="save" :disabled="saving || saveBlocked"
                :style="{padding:'8px 16px',background: saveBlocked ? 'var(--surface-3)' : 'var(--blue)',
                         color: saveBlocked ? 'var(--text-3)' : '#fff',border:'none',borderRadius:'8px',cursor: saveBlocked ? 'not-allowed' : 'pointer',fontSize:'13px'}">
          {{ saving ? 'Saving…' : 'Save configuration' }}
        </button>
        <span v-if="saveBlocked && missingVendors.length" style="font-size:12px;color:var(--amber,#d97706);">
          Provide keys for: {{ missingVendors.join(', ') }}
        </span>
        <span style="font-size:12px;color:var(--text-3);">{{ syncLabel }}</span>
      </div>
    </main>

    <main v-show="activeTab==='monitor'" style="max-width:900px;margin:0 auto;padding:22px 18px;">
      <MonitorTab :dark="dark" />
    </main>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from "vue"
import * as api from "@/api"
import { LIGHT_VARS, DARK_VARS, isDark } from "@/theme"
import { deriveMode, reorder, presetToModels, missingVendorKeys, validatePool } from "@/llm/pool"
import MonitorTab from "@/views/MonitorTab.vue"

// Theme — reactive to OS changes (mirrors ChatView.vue pattern)
const theme = ref(localStorage.getItem("jarvis-theme") || "system")
const prefersDark = ref(false)
let _mq = null
function onColorScheme(e) { prefersDark.value = e.matches }
const dark = computed(() => isDark(theme.value, prefersDark.value))
const paletteVars = computed(() => (dark.value ? DARK_VARS : LIGHT_VARS))

const activeTab = ref("manage")

// State
const cfg = ref({ models: [], preset: "", routing_mode: "failover", proxy_active: false })
const catalog = ref([])
const models = ref([])          // current ordered pool rows (used for display + save)
const err = ref("")
const saving = ref(false)
const sync = ref({ last_sync_status: "", pending: false })
let pollTimer = null

// Preset selection state
const selectedPreset = ref("")  // key of currently chosen preset card
const keysByVendor = ref({})    // vendor -> api_key (entered progressively)

// Derived
const mode = computed(() => deriveMode(models.value, selectedPreset.value))
const syncLabel = computed(() => sync.value.pending ? "Syncing to your agent…" : (sync.value.last_sync_status || ""))

const singleVendorPresets = computed(() => catalog.value.filter(c => c.kind === "single_vendor"))
const crossVendorPresets = computed(() => catalog.value.filter(c => c.kind === "cross_vendor"))

// Vendors required by the currently-selected preset entry
const selectedEntry = computed(() => catalog.value.find(c => c.key === selectedPreset.value) || null)
const vendorsForPreset = computed(() => {
  const e = selectedEntry.value
  if (!e) return []
  if (e.vendors && e.vendors.length) return e.vendors
  const seen = new Set()
  const out = []
  for (const m of (e.models || [])) { if (!seen.has(m.provider)) { seen.add(m.provider); out.push(m.provider) } }
  return out
})
const missingVendors = computed(() => {
  const e = selectedEntry.value
  if (!e) return []
  return missingVendorKeys(e, keysByVendor.value)
})

// Save is blocked when a preset is selected but not all vendor keys are provided
const saveBlocked = computed(() => selectedPreset.value && missingVendors.value.length > 0)

function presetLabel(key) { return (catalog.value.find((c) => c.key === key) || {}).label || key }
function move(i, d) { models.value = reorder(models.value, i, i + d) }
function remove(i) { models.value = models.value.filter((_, j) => j !== i) }
function _err(e) { return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong." }

function selectPreset(entry) {
  selectedPreset.value = entry.key
  cfg.value.preset = entry.key
  // Rebuild models from the preset with whatever keys we have so far
  models.value = presetToModels(entry, keysByVendor.value)
}

function clearPreset() {
  selectedPreset.value = ""
  cfg.value.preset = ""
  // Keep current models as the starting point for custom editing
}

// In custom mode: add a blank row to the shared models array
function addModel() {
  models.value = [...models.value, { provider: "", model: "", api_key: "", has_key: false, order: models.value.length }]
}

// Whenever vendor keys change while a preset is active, refresh models preview
watch(keysByVendor, () => {
  if (selectedPreset.value) {
    const e = selectedEntry.value
    if (e) models.value = presetToModels(e, keysByVendor.value)
  }
}, { deep: true })

async function load() {
  try {
    cfg.value = (await api.getLlmConfig()) || cfg.value
    // api_key is never returned by the server; has_key signals whether one is stored
    models.value = (cfg.value.models || []).map(m => ({
      provider: m.provider,
      model: m.model,
      api_key: "",
      has_key: m.has_key || false,
      order: m.order || 0
    }))
    selectedPreset.value = cfg.value.preset || ""
  } catch (e) { err.value = _err(e) }
  try { catalog.value = (await api.getPresetCatalog()) || [] } catch (e) { /* backend bundled fallback */ }
}

async function save() {
  err.value = ""
  // models is the single source of truth for both preset and custom mode
  const saveModels = models.value
  const savePreset = selectedPreset.value || null

  const v = validatePool(saveModels, savePreset)
  if (!v.ok) { err.value = v.error; return }

  saving.value = true
  try {
    await api.saveLlmPool(saveModels, savePreset, "failover")
    startPolling()
    await load()
  } catch (e) { err.value = _err(e) } finally { saving.value = false }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      sync.value = await api.getLlmSyncStatus()
      if (!sync.value.pending) stopPolling()
    } catch (e) { stopPolling() }
  }, 3000)
}
function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null } }

onMounted(() => {
  load()
  _mq = window.matchMedia("(prefers-color-scheme: dark)")
  prefersDark.value = _mq.matches
  _mq.addEventListener("change", onColorScheme)
})
onBeforeUnmount(() => {
  stopPolling()
  _mq?.removeEventListener("change", onColorScheme)
})
</script>
