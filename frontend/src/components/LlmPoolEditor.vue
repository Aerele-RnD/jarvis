<template>
  <!-- Reusable LLM-pool editor. Renders the 3-mode SETUP UI (Quick | Preset |
       Custom) over the unified proxy-pool model and persists via saveLlmPool.
       Self-loads its config on mount (seeded through seedRowsFromConfig into the
       canonical camelCase row shape). Expects an ancestor to supply the theme
       CSS vars (--surface, --text, …); uses only tokens, no hard-coded colors.
       Consumers: AiView (manage tab) now, AccountView + onboarding later. -->
  <div class="jv-llm-editor" style="font-family:inherit;color:var(--text);">
    <div v-if="err" style="color:var(--red);font-size:13px;margin-bottom:12px;">{{ err }}</div>

    <!-- Setup mode tabs + derived Direct/Proxy badge — hidden when the host
         allows only one mode (onboarding's quick-only editor). -->
    <div v-if="!singleMode" style="display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap;">
      <div role="tablist" style="display:inline-flex;border:1px solid var(--border);border-radius:9px;overflow:hidden;">
        <button v-for="t in modeTabs" :key="t.value" role="tab" :aria-selected="llmMode===t.value"
                @click="setMode(t.value)" :disabled="!editable"
                :style="{fontSize:'14px',padding:'10px 18px',border:'none',
                         cursor: editable ? 'pointer' : 'default',
                         background: llmMode===t.value ? 'var(--blue-bg)' : 'var(--surface)',
                         color: llmMode===t.value ? 'var(--blue)' : 'var(--text-3)',
                         fontWeight: llmMode===t.value ? '600' : '400'}">{{ t.label }}</button>
      </div>
      <span :style="{fontSize:'12px',fontWeight:600,padding:'4px 11px',borderRadius:'20px',
             background: badgeMode==='proxy' ? 'var(--green-bg)' : 'var(--surface-2)',
             color: badgeMode==='proxy' ? 'var(--green)' : 'var(--text-3)'}">
        {{ badgeMode === 'proxy' ? 'Proxy (failover)' : 'Direct' }}
      </span>
    </div>

    <!-- ===================== PRESET ===================== -->
    <section v-if="llmMode==='preset'" style="margin-bottom:18px;">
      <p v-if="!catalog.length" style="font-size:14px;color:var(--text-3);margin:0 0 12px;">
        Couldn't load presets — use <b>Quick</b> or <b>Custom</b>.
      </p>
      <div v-else style="max-height:440px;overflow-y:auto;padding-right:4px;">
        <!-- single_vendor presets -->
        <div v-if="singleVendorPresets.length" style="margin-bottom:10px;">
          <div style="font-size:13px;font-weight:600;color:var(--text-2);text-transform:uppercase;letter-spacing:.03em;margin-bottom:9px;">Single-vendor resilience</div>
          <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;">
            <button v-for="entry in singleVendorPresets" :key="entry.key"
                    @click="selectPreset(entry)" :disabled="!editable" :style="presetCardStyle(entry)">
              <div style="font-size:14px;font-weight:600;">{{ entry.label }}</div>
              <div style="font-size:13px;color:var(--text-2);margin-top:4px;line-height:1.45;">{{ entry.blurb }}</div>
            </button>
          </div>
        </div>
        <!-- cross_vendor presets -->
        <div v-if="crossVendorPresets.length">
          <div style="font-size:13px;font-weight:600;color:var(--text-2);text-transform:uppercase;letter-spacing:.03em;margin:14px 0 9px;">Cross-vendor strategies</div>
          <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;">
            <button v-for="entry in crossVendorPresets" :key="entry.key"
                    @click="selectPreset(entry)" :disabled="!editable" :style="presetCardStyle(entry)">
              <div style="font-size:14px;font-weight:600;">{{ entry.label }}</div>
              <div style="font-size:13px;color:var(--text-2);margin-top:4px;line-height:1.45;">{{ entry.blurb }}</div>
            </button>
          </div>
        </div>
      </div>

      <!-- Progressive vendor key fields for the chosen preset (all-or-nothing) -->
      <div v-if="selectedPreset && vendorsForPreset.length"
           style="margin-top:12px;padding:12px;background:var(--amber-bg);border:1px solid var(--amber-bd);border-radius:8px;">
        <div style="font-size:13px;color:var(--amber);font-weight:600;margin-bottom:8px;">
          Provide API keys for this preset:
        </div>
        <div v-for="vendor in vendorsForPreset" :key="vendor" style="margin-bottom:8px;">
          <label :style="{fontSize:'12px',color:'var(--text-2)',display:'block',marginBottom:'3px'}">
            {{ providerLabel(vendor) }} API key<span v-if="missingVendors.includes(vendor)" style="color:var(--red)"> *</span>
          </label>
          <input :value="keysByVendor[vendor] || ''" @input="keysByVendor[vendor] = $event.target.value"
                 type="password" :disabled="!editable" :placeholder="providerLabel(vendor) + ' API key'"
                 style="width:100%;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;box-sizing:border-box;" />
        </div>
      </div>
    </section>

    <!-- ================ QUICK / CUSTOM (shared rows) ================ -->
    <section v-else style="margin-bottom:18px;">
      <p v-if="llmMode==='quick'" style="font-size:14px;color:var(--text-3);margin:0 0 12px;">
        A single model, sent directly to the provider.<template v-if="canPool"> Need multiple models with failover? Use <b>Preset</b> or <b>Custom</b>.</template><template v-else> You can add more models and automatic failover later from My Account.</template>
      </p>
      <div v-else style="font-size:13px;font-weight:600;color:var(--text-2);margin-bottom:8px;letter-spacing:.03em;text-transform:uppercase;">
        Custom failover pool
      </div>

      <div v-if="!editorRows.length" style="font-size:13px;color:var(--text-3);padding:8px 0;">No models yet — add one below.</div>

      <div v-for="(m,i) in editorRows" :key="i"
           style="border:1px solid var(--border);border-radius:9px;padding:10px;margin-bottom:8px;background:var(--surface-1);">

        <!-- Row head: credential-type toggle (+ reorder/remove in Custom) -->
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
          <div style="display:inline-flex;border:1px solid var(--border);border-radius:7px;overflow:hidden;">
            <button v-for="opt in credTypes" :key="opt.value" @click="setCredType(m, opt.value)" :disabled="!editable"
                    :style="{fontSize:'12px',padding:'5px 11px',border:'none',cursor: editable ? 'pointer' : 'default',
                             background: m.credentialType===opt.value ? 'var(--blue-bg)' : 'var(--surface)',
                             color: m.credentialType===opt.value ? 'var(--blue)' : 'var(--text-3)',
                             fontWeight: m.credentialType===opt.value ? '600' : '400'}">{{ opt.label }}</button>
          </div>
          <div v-if="isMulti" style="margin-left:auto;display:flex;gap:6px;">
            <button @click="move(i,-1)" :disabled="!editable || i===0" title="Up"
                    :style="{border:'1px solid var(--border)',background:'var(--surface)',borderRadius:'5px',width:'26px',height:'26px',cursor:'pointer',fontSize:'11px',opacity: i===0 ? '0.35' : '1'}">▲</button>
            <button @click="move(i,1)" :disabled="!editable || i===editorRows.length-1" title="Down"
                    :style="{border:'1px solid var(--border)',background:'var(--surface)',borderRadius:'5px',width:'26px',height:'26px',cursor:'pointer',fontSize:'11px',opacity: i===editorRows.length-1 ? '0.35' : '1'}">▼</button>
            <button @click="remove(i)" :disabled="!editable" title="Remove"
                    style="border:1px solid var(--red-bd);background:var(--red-bg);color:var(--red);border-radius:5px;width:26px;height:26px;cursor:pointer;font-size:12px;">✕</button>
          </div>
        </div>

        <!-- API-key credential: provider (select) / model (datalist) / api_key / base_url -->
        <div v-if="m.credentialType!=='subscription'" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <select v-model="m.provider" @change="onProviderChange(m)" :disabled="!editable" title="Provider"
                  style="flex:1;min-width:120px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;">
            <option v-for="p in providerOptions" :key="p" :value="p">{{ p }}</option>
          </select>
          <input v-model="m.model" :list="'jv-dl-'+i" :disabled="!editable" placeholder="Model ID (e.g. gpt-4o)"
                 style="flex:1.5;min-width:120px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
          <datalist :id="'jv-dl-'+i">
            <option v-for="s in modelSuggestionsForProvider(m.provider)" :key="s" :value="s"></option>
          </datalist>
          <input v-model="m.apiKey" :disabled="!editable" type="password"
                 :placeholder="m.hasKey ? 'key set — re-enter to change' : 'API key'"
                 style="flex:1.5;min-width:120px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
          <input v-model="m.baseUrl" :disabled="!editable" placeholder="Base URL (OpenAI-compatible)"
                 style="flex:1.5;min-width:120px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
        </div>

        <!-- Chat-subscription credential. In the simplified (onboarding) editor
             the provider is enough: the Model ID field + rotation dropdown are
             hidden (model auto-defaults per provider), leaving just the provider
             picker + connect. The full account editor keeps all three. -->
        <div v-else>
          <label v-if="singleMode" style="display:block;font-size:12px;color:var(--text-2);margin-bottom:4px;">Chat subscription provider</label>
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap;">
            <input v-if="!singleMode" v-model="m.model" :list="'jv-subdl-'+i" :disabled="!editable" placeholder="Model ID (e.g. gpt-5.5)"
                   style="flex:2;min-width:120px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
            <datalist v-if="!singleMode" :id="'jv-subdl-'+i">
              <option v-for="s in (SUB_MODEL_SUGGESTIONS[m.upstream] || [])" :key="s" :value="s"></option>
            </datalist>
            <select v-model="m.upstream" @change="onUpstreamChange(m)" :disabled="!editable" title="Provider"
                    style="flex:1;min-width:100px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;">
              <option v-for="o in upstreamOpts" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
            <select v-if="!singleMode" v-model="m.rotation" :disabled="!editable" title="Account rotation"
                    style="flex:1.2;min-width:110px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;">
              <option v-for="o in rotationOpts" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </div>

          <!-- Connected accounts -->
          <div v-if="m.accounts && m.accounts.length" style="display:flex;flex-direction:column;gap:5px;margin-bottom:8px;">
            <div v-for="(a, ai) in m.accounts" :key="a.account_ref || ai"
                 style="display:flex;align-items:center;gap:8px;padding:5px 9px;border:1px solid var(--green-bd);background:var(--green-bg);border-radius:6px;">
              <span style="font-size:12px;font-weight:600;color:var(--green);">connected</span>
              <span style="font-size:14px;color:var(--text);">{{ accountLabel(a) }}</span>
              <span style="font-size:12px;color:var(--text-3);">{{ a.upstream || 'openai' }}</span>
              <span style="margin-left:auto;display:flex;gap:6px;align-items:center;">
                <button v-if="editable && !singleMode" @click="startConnect(m, ai)" title="Re-authorize this subscription — mint fresh tokens"
                        style="border:1px solid var(--border-2);background:var(--surface);color:var(--blue);border-radius:5px;padding:3px 9px;cursor:pointer;font-size:12px;">Reconnect</button>
                <button v-if="editable" @click="removeAccount(m, ai)" title="Remove account"
                        style="border:1px solid var(--red-bd);background:var(--red-bg);color:var(--red);border-radius:5px;width:22px;height:22px;cursor:pointer;font-size:12px;">✕</button>
              </span>
            </div>
          </div>
          <div v-else style="font-size:13px;color:var(--text-3);margin-bottom:8px;">No accounts connected yet.</div>

          <!-- Inline paste-back connect flow -->
          <div v-if="m._connect && m._connect.open"
               style="padding:10px;background:var(--surface-2);border:1px solid var(--border);border-radius:8px;margin-bottom:8px;">
            <div v-if="m._connect.authorizeUrl" style="display:flex;flex-direction:column;gap:8px;">
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
                <a :href="m._connect.authorizeUrl" target="_blank" rel="noopener noreferrer"
                   style="font-size:14px;color:var(--blue);text-decoration:none;font-weight:600;">Open sign-in ↗</a>
                <button @click="copyAuthorizeUrl(m)" title="Copy URL"
                        style="font-size:13px;padding:4px 10px;border:1px solid var(--border);border-radius:6px;cursor:pointer;background:var(--surface);color:var(--text-2);">
                  {{ m._connect.copied ? 'Copied ✓' : 'Copy' }}
                </button>
              </div>
              <input v-model="m._connect.pastedUrl" placeholder="Paste the URL after you sign in"
                     style="width:100%;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;box-sizing:border-box;" />
              <div style="display:flex;gap:8px;">
                <button @click="finishConnect(m)" :disabled="m._connect.loading"
                        :style="{padding:'6px 14px',fontSize:'12.5px',border:'none',borderRadius:'6px',
                                 cursor: m._connect.loading ? 'not-allowed' : 'pointer',
                                 background:'var(--blue)',color:'#fff',opacity: m._connect.loading ? '0.6' : '1'}">
                  {{ m._connect.loading ? 'Connecting…' : 'Connect' }}
                </button>
                <button @click="closeConnect(m)"
                        style="padding:9px 16px;font-size:14px;border:1px solid var(--border);border-radius:6px;cursor:pointer;background:var(--surface);color:var(--text-2);">Cancel</button>
              </div>
            </div>
            <div v-else style="font-size:13px;color:var(--text-2);">Starting sign-in…</div>
            <div v-if="m._connect.error" style="margin-top:6px;font-size:13px;color:var(--red);">{{ m._connect.error }}</div>
          </div>

          <!-- Simplified onboarding editor hides rotation, so it also caps the row
               at a single account (no unusable multi-account-without-rotation state):
               hide "+ Connect account" once one is connected. -->
          <button v-if="editable && (!singleMode || !(m.accounts && m.accounts.length))" @click="startConnect(m)"
                  :disabled="m._connect && m._connect.loading && !m._connect.authorizeUrl"
                  style="font-size:14px;color:var(--blue);background:transparent;border:1px dashed var(--border-2);border-radius:7px;padding:9px 16px;cursor:pointer;">
            + Connect account
          </button>
        </div>
      </div>

      <button v-if="isMulti && editable" @click="addModel"
              style="font-size:14px;color:var(--blue);background:transparent;border:1px dashed var(--border-2);border-radius:7px;padding:9px 16px;cursor:pointer;width:100%;">
        + Add model
      </button>
    </section>

    <!-- Save bar + sync status -->
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
      <button v-if="editable" @click="save" :disabled="saving || saveBlocked"
              :style="{padding:'12px 24px',background: saveBlocked ? 'var(--surface-3)' : 'var(--blue)',
                       color: saveBlocked ? 'var(--text-3)' : '#fff',border:'none',borderRadius:'9px',
                       cursor: saveBlocked ? 'not-allowed' : 'pointer',fontSize:'15px',fontWeight:'600'}">
        {{ saving ? 'Saving…' : 'Save configuration' }}
      </button>
      <span v-if="saveBlocked && missingVendors.length" style="font-size:13px;color:var(--amber);">
        Provide keys for: {{ missingVendors.map(providerLabel).join(', ') }}
      </span>
      <span style="font-size:13px;color:var(--text-3);">{{ syncLabel }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from "vue"
import * as api from "@/api"
import {
  deriveMode, reorder, presetToModels, missingVendorKeys, validatePool,
  PROVIDER_LABELS, providerLabel, seedRowsFromConfig, defaultSubscriptionModel, SUB_MODEL_SUGGESTIONS,
} from "@/llm/pool"
import { errMessage as _err } from "@/lib/errors"

const props = defineProps({
  editable: { type: Boolean, default: true },
  // Which setup tabs to expose. Default = the full 3-mode editor (Account page).
  // Onboarding passes ["quick"] to offer a single direct model and hide the
  // proxy-pool Preset/Custom tabs + the Direct/Proxy badge — faster signup, no
  // failover/pooling decisions up front (users configure that later in Account).
  modes: { type: Array, default: () => ["quick", "preset", "custom"] },
})
const emit = defineEmits(["saved"])

// ---- state ---------------------------------------------------------------
const cfg = ref({ models: [], preset: "", routing_mode: "failover", proxy_active: false })
const catalog = ref([])
const rows = ref([])              // canonical camelCase rows (single source of truth)
const llmMode = ref("quick")      // "quick" | "preset" | "custom"
const selectedPreset = ref("")
const keysByVendor = ref({})
const err = ref("")
const saving = ref(false)
const sync = ref({ last_sync_status: "", pending: false })
let pollTimer = null

const ALL_MODE_TABS = [
  { value: "quick", label: "Quick" },
  { value: "preset", label: "Preset" },
  { value: "custom", label: "Custom" },
]
// Only the tabs the host allows, in canonical order.
const modeTabs = computed(() => ALL_MODE_TABS.filter((t) => props.modes.includes(t.value)))
// With a single allowed mode the tab bar + Direct/Proxy badge are just noise —
// hide them and render that mode's body directly (onboarding's quick-only editor).
const singleMode = computed(() => modeTabs.value.length <= 1)
// Whether any proxy-pool tab (Preset/Custom) is reachable — gates the Quick hint
// copy so it never points at tabs that aren't there.
const canPool = computed(() => props.modes.includes("preset") || props.modes.includes("custom"))
const credTypes = [
  { value: "api_key", label: "API key" },
  { value: "subscription", label: "Chat subscription" },
]
const rotationOpts = [
  { value: "sticky", label: "Sticky" },
  { value: "round_robin", label: "Round robin" },
  { value: "least_used", label: "Least used" },
]
const upstreamOpts = [
  { value: "openai", label: "OpenAI" },
  { value: "google", label: "Google" },
]
// Provider dropdown fed by the shared PROVIDER_LABELS (id⇄label). Rows store the
// display LABEL as `provider` (matches seedRowsFromConfig + the desk page).
const providerOptions = PROVIDER_LABELS.map((p) => p.label)

// ---- model-id suggestions (ported verbatim from jarvis_account.js) -------
const STATIC_MODEL_SUGGESTIONS = {
  "Anthropic": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"],
  "OpenAI": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-4o"],
  "Google Gemini": ["gemini-2.5-pro", "gemini-3.5-flash", "gemini-3.1-flash-lite"],
  "Mistral": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
  "Groq": ["llama-3.3-70b-versatile"],
  "Together AI": ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
  "DeepSeek": ["deepseek-chat"],
  "Moonshot (Kimi)": ["kimi-k2.6"],
  "OpenRouter": ["anthropic/claude-sonnet-4-6", "openai/gpt-5.5"],
  "Ollama (local)": ["qwen2.5:3b", "qwen2.5:0.5b", "llama3"],
  "OpenAI-Compatible": ["claude-sonnet-4-6", "gpt-4o", "qwen2.5:3b", "llama3"],
}
const PROVIDER_DEFAULTS = {
  "Anthropic": { model: "claude-sonnet-4-6", baseUrl: "https://api.anthropic.com" },
  "OpenAI": { model: "gpt-4o", baseUrl: "https://api.openai.com/v1" },
  "Google Gemini": { model: "gemini-2.5-pro", baseUrl: "https://generativelanguage.googleapis.com" },
  "Mistral": { model: "mistral-large-latest", baseUrl: "https://api.mistral.ai/v1" },
  "Groq": { model: "llama-3.3-70b-versatile", baseUrl: "https://api.groq.com/openai/v1" },
  "Together AI": { model: "meta-llama/Llama-3.3-70B-Instruct-Turbo", baseUrl: "https://api.together.xyz/v1" },
  "DeepSeek": { model: "deepseek-chat", baseUrl: "https://api.deepseek.com" },
  "Moonshot (Kimi)": { model: "kimi-k2.6", baseUrl: "https://api.moonshot.ai/v1" },
  "OpenRouter": { model: "anthropic/claude-sonnet-4-6", baseUrl: "https://openrouter.ai/api/v1" },
  "Ollama (local)": { model: "llama3", baseUrl: "http://host.docker.internal:11434/v1" },
  "vLLM (local)": { model: "", baseUrl: "" },
  "OpenAI-Compatible": { model: "", baseUrl: "" },
}
function catalogVendorLabel(vid) { return vid === "gemini" ? "Google Gemini" : providerLabel(vid) }
function modelSuggestionsForProvider(provider) {
  const label = providerLabel(provider || "")
  const out = []
  const push = (id) => { if (id && out.indexOf(id) === -1) out.push(id) }
  ;(catalog.value || []).forEach((e) => (e.models || []).forEach((m) => {
    if (catalogVendorLabel(m.provider) === label) push(m.model)
  }))
  ;(STATIC_MODEL_SUGGESTIONS[label] || []).forEach(push)
  push((PROVIDER_DEFAULTS[label] || {}).model)
  return out
}

// ---- derived -------------------------------------------------------------
const isMulti = computed(() => llmMode.value === "custom")
const editorRows = computed(() => isMulti.value ? rows.value : rows.value.slice(0, 1))
const singleVendorPresets = computed(() => catalog.value.filter((c) => c.kind === "single_vendor"))
const crossVendorPresets = computed(() => catalog.value.filter((c) => c.kind === "cross_vendor"))
const selectedEntry = computed(() => catalog.value.find((c) => c.key === selectedPreset.value) || null)
const vendorsForPreset = computed(() => {
  const e = selectedEntry.value
  if (!e) return []
  if (e.vendors && e.vendors.length) return e.vendors
  const seen = new Set(), out = []
  for (const m of (e.models || [])) if (!seen.has(m.provider)) { seen.add(m.provider); out.push(m.provider) }
  return out
})
const missingVendors = computed(() => {
  const e = selectedEntry.value
  return e ? missingVendorKeys(e, keysByVendor.value) : []
})
const saveBlocked = computed(() => llmMode.value === "preset" && !!selectedPreset.value && missingVendors.value.length > 0)

// Direct/Proxy badge — mirrors jarvis_account.js renderModeBadge().
// Quick is always Direct (single model); Preset is Proxy once chosen; Custom
// derives from the count of valid rows via the shared deriveMode helper.
const badgeMode = computed(() => {
  if (llmMode.value === "quick") return "direct"
  if (llmMode.value === "preset") return selectedPreset.value ? "proxy" : "direct"
  const valid = rows.value.filter((r) => r && (
    r.credentialType === "subscription" ? (r.model || "").trim() : ((r.provider || "").trim() && (r.model || "").trim())
  ))
  return deriveMode(valid, null)
})
const syncLabel = computed(() => {
  if (sync.value.pending) return "Syncing to your agent…"
  const s = sync.value.last_sync_status || ""
  return s ? `Last sync: ${s}` : ""
})

// ---- helpers -------------------------------------------------------------
function blankConnect() { return { open: false, loading: false, error: "", copied: false, nonce: "", authorizeUrl: "", pastedUrl: "", reconnectIdx: null } }
function presetCardStyle(entry) {
  const on = selectedPreset.value === entry.key
  return {
    padding: "14px 16px", fontSize: "14px", cursor: props.editable ? "pointer" : "default", borderRadius: "10px", textAlign: "left",
    border: on ? "2px solid var(--blue)" : "1px solid var(--border)",
    background: on ? "var(--blue-bg)" : "var(--surface)",
    color: on ? "var(--blue)" : "var(--text)",
    opacity: entry.enabled === false ? "0.45" : "1",
    fontWeight: on ? "600" : "400",
  }
}

// Copy text to clipboard, with a graceful fallback for insecure (LAN HTTP)
// contexts where navigator.clipboard is undefined (ported from the desk page).
function copyTextWithFallback(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text)
  return new Promise((resolve, reject) => {
    const ta = document.createElement("textarea")
    ta.value = text; ta.style.position = "fixed"; ta.style.left = "-9999px"; ta.style.top = "0"
    document.body.appendChild(ta); ta.focus(); ta.select()
    try {
      const ok = document.execCommand("copy"); document.body.removeChild(ta)
      ok ? resolve() : reject(new Error("copy failed"))
    } catch (e) { document.body.removeChild(ta); reject(e) }
  })
}

function newRow() {
  return {
    provider: providerOptions[0] || "Anthropic", model: "", apiKey: "", baseUrl: "", hasKey: false,
    credentialType: "api_key", rotation: "sticky", upstream: "openai",
    accounts: [], _connect: blankConnect(), order: 0,
  }
}

function setMode(m) {
  llmMode.value = m
  if (m !== "preset") {
    selectedPreset.value = ""
    if (!rows.value.length) rows.value = [newRow()]
  }
}

function setCredType(m, type) {
  m.credentialType = type
  if (type === "subscription") {
    if (!m.rotation) m.rotation = "sticky"
    if (!m.upstream) m.upstream = "openai"
    if (!Array.isArray(m.accounts)) m.accounts = []
    if (!m._connect) m._connect = blankConnect()
    // Onboarding hides the model field — default it from the chosen provider so
    // validatePool + save still have a model id.
    if (singleMode.value) m.model = defaultSubscriptionModel(m.upstream)
  } else if (singleMode.value) {
    // Toggling back to API key in the simplified editor: drop the subscription
    // model id (hidden while on the subscription tab) so it doesn't linger under
    // an API-key provider it doesn't belong to.
    m.model = (PROVIDER_DEFAULTS[m.provider] || {}).model || ""
  }
}
function onProviderChange(m) {
  const d = PROVIDER_DEFAULTS[m.provider] || {}
  if (!(m.model || "").trim() && d.model) m.model = d.model
  if (!(m.baseUrl || "").trim() && d.baseUrl) m.baseUrl = d.baseUrl
}
// Provider switch on a subscription row in the simplified onboarding editor:
// re-default the (hidden) model AND drop any already-connected account, which is
// provider-specific — otherwise we'd save a model bound to the wrong provider's
// OAuth credential. A no-op elsewhere (full editor manages model/accounts itself).
function onUpstreamChange(m) {
  if (singleMode.value && m.credentialType === "subscription") {
    m.model = defaultSubscriptionModel(m.upstream)
    m.accounts = []
    m._connect = blankConnect()
  }
}
function move(i, d) { rows.value = reorder(rows.value, i, i + d) }
function remove(i) { rows.value = rows.value.filter((_, j) => j !== i) }
function removeAccount(m, idx) { m.accounts = (m.accounts || []).filter((_, j) => j !== idx) }
function addModel() { rows.value = [...rows.value, { ...newRow(), order: rows.value.length }] }

function selectPreset(entry) {
  selectedPreset.value = entry.key
  rows.value = seedFromPreset(entry)
}
function seedFromPreset(entry) {
  return presetToModels(entry, keysByVendor.value).map((m) => ({
    provider: providerLabel(m.provider), model: m.model, apiKey: m.api_key || "", baseUrl: "",
    hasKey: false, credentialType: "api_key", rotation: "sticky", upstream: "openai",
    accounts: [], _connect: blankConnect(), order: m.order,
  }))
}

// ---- connect flow (paste-back OAuth) -------------------------------------
function accountLabel(a) {
  // Show a real label / email; never surface the internal SUB_<hex> account ref.
  const l = (a && a.label) || ""
  if (l && !/^SUB_/i.test(l)) return l
  return (a && a.account_email) || "Account connected"
}
async function startConnect(m, reconnectIdx = null) {
  if (!m._connect) m._connect = blankConnect()
  // Simplified editor hides the model field — make sure a subscription row always
  // carries a model id so the connect flow never dead-ends on an unfillable field.
  if (singleMode.value && m.credentialType === "subscription" && !(m.model || "").trim()) {
    m.model = defaultSubscriptionModel(m.upstream)
  }
  if (!(m.model || "").trim()) {
    m._connect = { ...blankConnect(), open: true, error: "Enter a model id before connecting an account." }
    return
  }
  m._connect = { ...blankConnect(), open: true, loading: true, reconnectIdx }
  try {
    const provider = m.upstream === "google" ? "Google" : "OpenAI"
    const res = await api.beginPoolAccountSignin(provider, m.model.trim())
    // Backend returns an envelope: {ok:true, data:{nonce, authorize_url, …}} or
    // {ok:false, error:{code, message}}. Unwrap data; surface errors instead of
    // hanging on "Starting sign-in…".
    if (!res || res.ok === false) {
      m._connect.loading = false
      m._connect.error = (res && res.error && res.error.message) || "Couldn't start sign-in — try again."
      return
    }
    const d = res.data || {}
    m._connect.nonce = d.nonce
    m._connect.authorizeUrl = d.authorize_url
    m._connect.loading = false
  } catch (e) { m._connect.loading = false; m._connect.error = _err(e) }
}
async function finishConnect(m) {
  if (!m._connect || !m._connect.nonce) return
  if (!(m._connect.pastedUrl || "").trim()) { m._connect.error = "Paste the URL you were redirected to."; return }
  m._connect.loading = true; m._connect.error = ""
  try {
    const res = await api.completePoolAccountSignin(m._connect.nonce, m._connect.pastedUrl.trim())
    // Same {ok, data} envelope as begin — unwrap + surface errors.
    if (!res || res.ok === false) {
      m._connect.loading = false
      m._connect.error = (res && res.error && res.error.message) || "Couldn't connect the account — check the pasted URL and try again."
      return
    }
    const d = res.data || {}
    if (!Array.isArray(m.accounts)) m.accounts = []
    const acct = {
      upstream: m.upstream || "openai",
      account_ref: d.account_ref,
      label: d.label || d.account_email || d.account_ref,
      account_email: d.account_email || "",
      oauth_blob: d.oauth_blob || "",
      connected: true,
    }
    // Place the (re)connected account. The backend mints a fresh account_ref on
    // every sign-in, so it can't be a dedupe key: a per-account Reconnect refreshes
    // that exact slot (reconnectIdx); otherwise fold onto an existing account with
    // the same email; otherwise append a new one.
    const ri = m._connect.reconnectIdx
    const byEmail = acct.account_email
      ? m.accounts.findIndex((a) => a.account_email && a.account_email.toLowerCase() === acct.account_email.toLowerCase())
      : -1
    if (ri != null && ri >= 0 && ri < m.accounts.length) m.accounts.splice(ri, 1, acct)
    else if (byEmail >= 0) m.accounts.splice(byEmail, 1, acct)
    else m.accounts.push(acct)
    m._connect = blankConnect()
  } catch (e) { m._connect.loading = false; m._connect.error = _err(e) }
}
function closeConnect(m) { m._connect = blankConnect() }
function copyAuthorizeUrl(m) {
  const url = m._connect && m._connect.authorizeUrl
  if (!url) return
  copyTextWithFallback(url).then(() => {
    m._connect.copied = true
    setTimeout(() => { if (m._connect) m._connect.copied = false }, 1400)
  }).catch(() => { m._connect.error = "Could not copy — select the URL above and copy manually." })
}

// ---- load / save ---------------------------------------------------------
// Seed the canonical rows from get_llm_config, then augment each with the
// transient UI-only fields the editor needs (upstream + _connect). Seeded
// accounts carry no oauth_blob (never returned by the server) — reconnect to
// change; they render as "connected" via their label.
function seedRows(config) {
  return seedRowsFromConfig(config).map((r) => ({
    ...r,
    upstream: (r.accounts && r.accounts[0] && r.accounts[0].upstream) || "openai",
    accounts: (r.accounts || []).map((a) => ({ ...a, oauth_blob: "" })),
    _connect: blankConnect(),
  }))
}

async function load() {
  err.value = ""
  try {
    cfg.value = (await api.getLlmConfig()) || cfg.value
    rows.value = seedRows(cfg.value)
    selectedPreset.value = cfg.value.preset || ""
    keysByVendor.value = {}
    // Open on the tab that matches what's stored (mirrors seedLlmSetupFromConfig).
    if (selectedPreset.value) llmMode.value = "preset"
    else if (rows.value.length >= 2 || rows.value.some((r) => r.credentialType === "subscription")) llmMode.value = "custom"
    else { llmMode.value = "quick"; if (!rows.value.length) rows.value = [newRow()] }
    // Onboarding is quick-only (singleMode): collapse to a single editable row so
    // the editor is WYSIWYG. Quick-mode Save persists only rows[0], so keeping the
    // rest of a seeded multi-model/preset pool around would silently drop it. Also
    // clear any stored preset — quick can't represent one.
    if (singleMode.value) {
      llmMode.value = props.modes[0] || "quick"
      selectedPreset.value = ""
      rows.value = rows.value.length ? [rows.value[0]] : [newRow()]
    } else if (!props.modes.includes(llmMode.value)) {
      llmMode.value = props.modes[0] || "quick"
      selectedPreset.value = ""
      if (!rows.value.length) rows.value = [newRow()]
    }
  } catch (e) { err.value = _err(e) }
  try { sync.value = (await api.getLlmSyncStatus()) || sync.value } catch (e) { /* non-fatal */ }
  try { catalog.value = (await api.getPresetCatalog()) || [] } catch (e) { /* backend bundled fallback */ }
}

// Build the per-row backend shape save_llm_pool expects (matches AiView + desk).
function buildSaveModels(sourceRows) {
  return (sourceRows || []).map((r, i) => {
    if (r.credentialType === "subscription") {
      return {
        model: (r.model || "").trim(),
        order: i,
        subscription: {
          rotation: r.rotation || "sticky",
          accounts: (r.accounts || []).map((a) => ({
            upstream: a.upstream || "openai",
            account_ref: a.account_ref,
            label: a.label,
            oauth_blob: a.oauth_blob || "",
          })),
        },
      }
    }
    const m = { provider: (r.provider || "").trim(), model: (r.model || "").trim(), api_key: (r.apiKey || "").trim(), order: i }
    if (r.hasKey) m.has_key = true  // let validatePool + backend merge keep a stored key on re-save
    const b = (r.baseUrl || "").trim()
    if (b) m.base_url = b
    return m
  })
}

async function save() {
  err.value = ""
  let saveModels, savePreset
  if (llmMode.value === "preset") {
    const e = selectedEntry.value
    if (!e) { err.value = "Pick a preset."; return }
    saveModels = presetToModels(e, keysByVendor.value)
    savePreset = selectedPreset.value || null
  } else {
    // Quick saves a single-model pool (rows[0]); Custom saves the full pool.
    saveModels = buildSaveModels(llmMode.value === "quick" ? rows.value.slice(0, 1) : rows.value)
    savePreset = null
  }
  // Simplified editor hides the model id, so validatePool's "Model <id> needs a
  // connected account" would name a value the user never saw. Pre-check with a
  // clear message instead.
  if (singleMode.value && llmMode.value !== "preset") {
    const r0 = rows.value[0]
    if (r0 && r0.credentialType === "subscription" &&
        !((r0.accounts || []).some((a) => a && (a.oauth_blob || a.account_ref)))) {
      err.value = "Connect your account to continue."
      return
    }
  }
  const v = validatePool(saveModels, savePreset)
  if (!v.ok) { err.value = v.error; return }
  saving.value = true
  try {
    await api.saveLlmPool(saveModels, savePreset, "failover")
    try { sync.value = await api.getLlmSyncStatus() } catch (e) { /* keep prior */ }
    startPolling()
    emit("saved", sync.value)
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

// Refresh the preset preview whenever vendor keys change while a preset is active.
watch(keysByVendor, () => {
  if (llmMode.value === "preset" && selectedPreset.value) {
    const e = selectedEntry.value
    if (e) rows.value = seedFromPreset(e)
  }
}, { deep: true })

onMounted(load)
onBeforeUnmount(stopPolling)
</script>
