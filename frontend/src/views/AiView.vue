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
             background: mode==='proxy' ? 'var(--green-bg)' : 'var(--surface-2)',
             color: mode==='proxy' ? 'var(--green)' : 'var(--text-3)'}">
        {{ mode === 'proxy' ? 'Proxy' : 'Direct' }}<template v-if="cfg.proxy_active"> · active</template>
      </span>
      <button @click="toggleTheme" :title="dark ? 'Switch to light theme' : 'Switch to dark theme'"
              style="width:32px;height:32px;display:flex;align-items:center;justify-content:center;background:var(--surface);border:1px solid var(--border);border-radius:7px;cursor:pointer;flex:none;">
        <svg v-if="dark" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
        <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-2)" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
      </button>
    </header>

    <!-- Manage tab -->
    <main v-show="activeTab==='manage'" style="max-width:760px;margin:0 auto;padding:22px 18px;">
      <div v-if="err" style="color:var(--red);font-size:13px;margin-bottom:12px;">{{ err }}</div>

      <!-- Current pool: ordered list of active models -->
      <section style="background:var(--surface-1);border:1px solid var(--border);border-radius:10px;padding:16px;margin-bottom:18px;">
        <div style="font-size:12px;color:var(--text-3);margin-bottom:8px;">
          {{ cfg.preset ? presetLabel(cfg.preset) : 'Custom pool' }} · failover
        </div>
        <div v-if="!models.length" style="font-size:13px;color:var(--text-3);padding:8px 0;">No models configured yet.</div>
        <div v-for="(m,i) in models" :key="i"
             style="display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--border);">
          <span style="font-size:13px;font-weight:550;">{{ m.credential_type === 'subscription' ? 'subscription' : m.provider }} / {{ m.model }}</span>
          <span style="font-size:11px;color:var(--text-3);">{{ i === 0 ? 'runs every turn' : 'backup' }}</span>
          <div style="margin-left:auto;display:flex;gap:6px;">
            <button @click="move(i,-1)" :disabled="i===0" title="Up"
                    style="border:1px solid var(--border);background:var(--surface);border-radius:5px;width:24px;height:24px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:11px;"
                    :style="{opacity: i===0 ? '0.35' : '1'}">▲</button>
            <button @click="move(i,1)" :disabled="i===models.length-1" title="Down"
                    style="border:1px solid var(--border);background:var(--surface);border-radius:5px;width:24px;height:24px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:11px;"
                    :style="{opacity: i===models.length-1 ? '0.35' : '1'}">▼</button>
            <button @click="remove(i)" title="Remove"
                    style="border:1px solid var(--red-bd);background:var(--red-bg);color:var(--red);border-radius:5px;width:24px;height:24px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:11px;">✕</button>
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
                      background: selectedPreset===entry.key ? 'var(--blue-bg)' : 'var(--surface)',
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
                      background: selectedPreset===entry.key ? 'var(--blue-bg)' : 'var(--surface)',
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
             style="margin-top:12px;padding:12px;background:var(--amber-bg);border:1px solid var(--amber-bd);border-radius:8px;">
          <div style="font-size:12px;color:var(--amber);font-weight:600;margin-bottom:8px;">
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

      <!-- Custom "+ Add model" rows for Quick/Custom mode — binds to models directly.
           Each row is either an API-key credential or a Chat-subscription credential. -->
      <section v-if="!selectedPreset" style="margin-bottom:18px;">
        <div style="font-size:12px;font-weight:600;color:var(--text-2);margin-bottom:8px;letter-spacing:.03em;text-transform:uppercase;">Custom models</div>
        <div v-for="(m, i) in models" :key="i"
             style="border:1px solid var(--border);border-radius:9px;padding:10px;margin-bottom:8px;background:var(--surface-1);">

          <!-- Row head: credential-type pill toggle + remove -->
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
            <div style="display:inline-flex;border:1px solid var(--border);border-radius:7px;overflow:hidden;">
              <button v-for="opt in credTypes" :key="opt.value" @click="setCredType(m, opt.value)"
                      :style="{fontSize:'12px',padding:'5px 11px',border:'none',cursor:'pointer',
                               background: m.credential_type===opt.value ? 'var(--blue-bg)' : 'var(--surface)',
                               color: m.credential_type===opt.value ? 'var(--blue)' : 'var(--text-3)',
                               fontWeight: m.credential_type===opt.value ? '600' : '400'}">{{ opt.label }}</button>
            </div>
            <button @click="remove(i)" title="Remove"
                    style="margin-left:auto;border:1px solid var(--red-bd);background:var(--red-bg);color:var(--red);border-radius:5px;width:28px;height:28px;cursor:pointer;flex:none;">✕</button>
          </div>

          <!-- API-key credential: provider / model / api_key / base_url (unchanged) -->
          <div v-if="m.credential_type!=='subscription'" style="display:flex;gap:8px;align-items:center;">
            <input v-model="m.provider" placeholder="Provider (e.g. openai)"
                   style="flex:1;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
            <input v-model="m.model" placeholder="Model ID (e.g. gpt-4o)"
                   style="flex:1.5;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
            <input v-model="m.api_key" :placeholder="m.has_key ? 'key set — re-enter to change' : 'API key'" type="password"
                   style="flex:1.5;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
            <input v-model="m.base_url" placeholder="Base URL (OpenAI-compatible)"
                   style="flex:1.5;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
          </div>

          <!-- Chat-subscription credential: model + rotation + upstream + connected accounts -->
          <div v-else>
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
              <input v-model="m.model" placeholder="Model ID (e.g. gpt-5.5)"
                     style="flex:2;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
              <select v-model="m.upstream" title="Upstream"
                      style="flex:1;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;">
                <option value="openai">OpenAI</option>
                <option value="google">Google</option>
              </select>
              <select v-model="m.rotation" title="Account rotation"
                      style="flex:1.2;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;">
                <option value="sticky">Sticky</option>
                <option value="round_robin">Round robin</option>
                <option value="least_used">Least used</option>
              </select>
            </div>

            <!-- Connected accounts -->
            <div v-if="m.accounts && m.accounts.length" style="display:flex;flex-direction:column;gap:5px;margin-bottom:8px;">
              <div v-for="(a, ai) in m.accounts" :key="a.account_ref || ai"
                   style="display:flex;align-items:center;gap:8px;padding:5px 9px;border:1px solid var(--green-bd);background:var(--green-bg);border-radius:6px;">
                <span style="font-size:11px;font-weight:600;color:var(--green);">connected</span>
                <span style="font-size:12.5px;color:var(--text);">{{ a.label || a.account_ref }}</span>
                <span style="font-size:11px;color:var(--text-3);">{{ a.upstream }}</span>
                <button @click="removeAccount(m, ai)" title="Remove account"
                        style="margin-left:auto;border:1px solid var(--red-bd);background:var(--red-bg);color:var(--red);border-radius:5px;width:22px;height:22px;cursor:pointer;flex:none;font-size:11px;">✕</button>
              </div>
            </div>
            <div v-else style="font-size:12px;color:var(--text-3);margin-bottom:8px;">No accounts connected yet.</div>

            <!-- Inline paste-back connect flow -->
            <div v-if="m._connect && m._connect.open"
                 style="padding:10px;background:var(--surface-2);border:1px solid var(--border);border-radius:8px;margin-bottom:8px;">
              <div v-if="m._connect.authorizeUrl" style="display:flex;flex-direction:column;gap:8px;">
                <a :href="m._connect.authorizeUrl" target="_blank" rel="noopener noreferrer"
                   style="font-size:12.5px;color:var(--blue);text-decoration:none;font-weight:600;">Open sign-in ↗</a>
                <input v-model="m._connect.pastedUrl" placeholder="Paste the URL after you sign in"
                       style="width:100%;padding:6px 9px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;box-sizing:border-box;" />
                <div style="display:flex;gap:8px;">
                  <button @click="finishConnect(m)" :disabled="m._connect.loading"
                          :style="{padding:'6px 14px',fontSize:'12.5px',border:'none',borderRadius:'6px',
                                   cursor: m._connect.loading ? 'not-allowed' : 'pointer',
                                   background:'var(--blue)',color:'#fff',opacity: m._connect.loading ? '0.6' : '1'}">
                    {{ m._connect.loading ? 'Connecting…' : 'Connect' }}
                  </button>
                  <button @click="closeConnect(m)"
                          style="padding:6px 14px;font-size:12.5px;border:1px solid var(--border);border-radius:6px;cursor:pointer;background:var(--surface);color:var(--text-2);">Cancel</button>
                </div>
              </div>
              <div v-else style="font-size:12px;color:var(--text-2);">Starting sign-in…</div>
              <div v-if="m._connect.error" style="margin-top:6px;font-size:12px;color:var(--red);">{{ m._connect.error }}</div>
            </div>

            <button @click="startConnect(m)" :disabled="m._connect && m._connect.loading && !m._connect.authorizeUrl"
                    style="font-size:12.5px;color:var(--blue);background:transparent;border:1px dashed var(--border-2);border-radius:7px;padding:6px 14px;cursor:pointer;">
              + Connect account
            </button>
          </div>
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
        <span v-if="saveBlocked && missingVendors.length" style="font-size:12px;color:var(--amber);">
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
import { useTheme } from "@/composables/useTheme"
import { deriveMode, reorder, presetToModels, missingVendorKeys, validatePool } from "@/llm/pool"
import MonitorTab from "@/views/MonitorTab.vue"

// Theme — shared composable: honours "jarvis-theme" pref, cross-tab sync, OS live.
const { effectiveDark: dark, paletteVars, toggleTheme } = useTheme()

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

// Per-row credential-type pills
const credTypes = [
  { value: "api_key", label: "API key" },
  { value: "subscription", label: "Chat subscription" },
]

function presetLabel(key) { return (catalog.value.find((c) => c.key === key) || {}).label || key }
function move(i, d) { models.value = reorder(models.value, i, i + d) }
function remove(i) { models.value = models.value.filter((_, j) => j !== i) }
function _err(e) { return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong." }

// Blank transient state for the inline paste-back connect flow (never emitted on save).
function blankConnect() { return { open: false, loading: false, error: "", nonce: "", authorizeUrl: "", pastedUrl: "" } }

// Flip a row between API-key and Chat-subscription; backfill subscription defaults.
function setCredType(m, type) {
  m.credential_type = type
  if (type === "subscription") {
    if (!m.rotation) m.rotation = "sticky"
    if (!m.upstream) m.upstream = "openai"
    if (!Array.isArray(m.accounts)) m.accounts = []
    if (!m._connect) m._connect = blankConnect()
  }
}

function removeAccount(m, idx) { m.accounts = (m.accounts || []).filter((_, j) => j !== idx) }

function closeConnect(m) { m._connect = blankConnect() }

// Step 1 — begin: fetch an authorize_url + nonce, then show the paste-back box.
async function startConnect(m) {
  if (!m._connect) m._connect = blankConnect()
  if (!(m.model || "").trim()) {
    m._connect = { ...blankConnect(), open: true, error: "Enter a model id before connecting an account." }
    return
  }
  m._connect = { ...blankConnect(), open: true, loading: true }
  try {
    const provider = m.upstream === "google" ? "Google" : "OpenAI"
    const res = await api.beginPoolAccountSignin(provider, m.model.trim())
    m._connect.nonce = res.nonce
    m._connect.authorizeUrl = res.authorize_url
    m._connect.loading = false
  } catch (e) {
    m._connect.loading = false
    m._connect.error = _err(e)
  }
}

// Step 2 — complete: capture the account from the pasted redirect URL.
async function finishConnect(m) {
  if (!m._connect || !m._connect.nonce) return
  if (!(m._connect.pastedUrl || "").trim()) { m._connect.error = "Paste the URL you were redirected to."; return }
  m._connect.loading = true
  m._connect.error = ""
  try {
    const res = await api.completePoolAccountSignin(m._connect.nonce, m._connect.pastedUrl.trim())
    if (!Array.isArray(m.accounts)) m.accounts = []
    m.accounts.push({
      upstream: m.upstream || "openai",
      account_ref: res.account_ref,
      label: res.label || res.account_email || res.account_ref,
      oauth_blob: res.oauth_blob || "",
    })
    m._connect = blankConnect()
  } catch (e) {
    m._connect.loading = false
    m._connect.error = _err(e)
  }
}

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

// In custom mode: add a blank row to the shared models array. Rows default to
// the api_key credential type; subscription-only fields ride along harmlessly.
function addModel() {
  models.value = [...models.value, {
    provider: "", model: "", api_key: "", base_url: "", has_key: false,
    credential_type: "api_key", rotation: "sticky", upstream: "openai",
    accounts: [], _connect: blankConnect(), order: models.value.length,
  }]
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
    // Neither api_key nor oauth_blob is returned by the server; has_key / the
    // presence of an account signals a stored credential (re-enter/-connect to change).
    models.value = (cfg.value.models || []).map(m => {
      if (m.subscription) {
        const accounts = (m.subscription.accounts || []).map(a => ({
          upstream: a.upstream || "openai",
          account_ref: a.account_ref,
          label: a.label || a.account_email || a.account_ref,
          oauth_blob: "", // never returned — shown as "connected" via label
        }))
        return {
          provider: "", model: m.model, api_key: "", base_url: "", has_key: false,
          credential_type: "subscription",
          rotation: m.subscription.rotation || "sticky",
          upstream: (accounts[0] && accounts[0].upstream) || "openai",
          accounts, _connect: blankConnect(),
          order: m.order || 0,
        }
      }
      return {
        provider: m.provider,
        model: m.model,
        api_key: "",
        base_url: m.base_url || "",
        has_key: m.has_key || false,
        credential_type: "api_key", rotation: "sticky", upstream: "openai",
        accounts: [], _connect: blankConnect(),
        order: m.order || 0,
      }
    })
    selectedPreset.value = cfg.value.preset || ""
  } catch (e) { err.value = _err(e) }
  try { catalog.value = (await api.getPresetCatalog()) || [] } catch (e) { /* backend bundled fallback */ }
}

async function save() {
  err.value = ""
  // models is the single source of truth for both preset and custom mode.
  // Emit the per-row backend shape: api_key rows unchanged; subscription rows
  // as { model, order, subscription: { rotation, accounts } } (no provider/api_key/base_url).
  const saveModels = models.value.map((m, i) => {
    if (m.credential_type === "subscription") {
      return {
        model: (m.model || "").trim(),
        order: m.order ?? i,
        subscription: {
          rotation: m.rotation || "sticky",
          accounts: (m.accounts || []).map(a => ({
            upstream: a.upstream || "openai",
            account_ref: a.account_ref,
            label: a.label,
            oauth_blob: a.oauth_blob || "",
          })),
        },
      }
    }
    // api_key row — strip UI-only fields, keep the existing emitted shape.
    const { credential_type, rotation, upstream, accounts, _connect, ...rest } = m
    return rest
  })
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
})
onBeforeUnmount(() => {
  stopPolling()
})
</script>
