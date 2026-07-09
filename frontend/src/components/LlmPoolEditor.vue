<template>
  <!-- Reusable LLM-pool editor. Renders the 3-mode SETUP UI (Quick | Preset |
       Custom) over the unified proxy-pool model and persists via saveLlmPool.
       Self-loads its config on mount (seeded through seedRowsFromConfig into the
       canonical camelCase row shape). Expects an ancestor to supply the theme
       CSS vars (--surface, --text, …); uses only tokens, no hard-coded colors.
       Consumers: AiView (manage tab) now, AccountView + onboarding later. -->
  <div class="jv-llm-editor" style="font-family:inherit;color:var(--text);">
    <div v-if="err" style="color:var(--red);font-size:13px;margin-bottom:12px;">{{ err }}</div>

    <!-- Setup mode tabs + derived Direct/Proxy badge - hidden when the host
         allows only one mode (onboarding's quick-only editor). -->
    <div v-if="!singleMode" style="display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap;">
      <div role="tablist" style="display:inline-flex;border:1px solid var(--border);border-radius:9px;overflow:hidden;">
        <button v-for="t in modeTabs" :key="t.value" role="tab" :aria-selected="llmMode===t.value"
                @click="setMode(t.value)" :disabled="!editable || (t.value==='quick' && quickLocked)"
                :title="t.value==='quick' && quickLocked ? 'Your pool has multiple models - edit them in Custom. Remove models to switch to Quick.' : ''"
                :style="{fontSize:'14px',padding:'10px 18px',border:'none',
                         cursor: (!editable || (t.value==='quick' && quickLocked)) ? 'not-allowed' : 'pointer',
                         opacity: (t.value==='quick' && quickLocked) ? '0.4' : '1',
                         background: llmMode===t.value ? 'var(--blue-bg)' : 'var(--surface)',
                         color: llmMode===t.value ? 'var(--blue)' : 'var(--text-3)',
                         fontWeight: llmMode===t.value ? '600' : '400'}">{{ t.label }}</button>
      </div>
      <span v-if="badgeLabel" style="font-size:12px;font-weight:600;padding:4px 11px;border-radius:20px;background:var(--green-bg);color:var(--green);">
        {{ badgeLabel }}
      </span>
    </div>

    <!-- ===================== PRESET ===================== -->
    <section v-if="llmMode==='preset'" style="margin-bottom:18px;">
      <p v-if="!catalog.length" style="font-size:14px;color:var(--text-3);margin:0 0 12px;">
        Couldn't load presets. Use <b>Quick</b> or <b>Custom</b>.
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
      <!-- Onboarding (singleMode) drops this hint line: the step's own subtitle
           ("Pick which AI powers Jarvis…") already covers it, per the preview. -->
      <p v-if="llmMode==='quick' && !singleMode" style="font-size:14px;color:var(--text-3);margin:0 0 12px;">
        <template v-if="rows[0] && rows[0].credentialType === 'subscription'">A single chat subscription, served through the managed proxy.</template><template v-else>A single model, sent directly to the provider.</template><template v-if="canPool"> Need multiple models with failover? Use <b>Preset</b> or <b>Custom</b>.</template><template v-else> You can add more models and automatic failover later from My Account.</template>
      </p>
      <div v-else style="font-size:13px;font-weight:600;color:var(--text-2);margin-bottom:8px;letter-spacing:.03em;text-transform:uppercase;">
        Custom failover pool
      </div>

      <div v-if="!editorRows.length" style="font-size:13px;color:var(--text-3);padding:8px 0;">No models yet. Add one below.</div>

      <!-- Onboarding (singleMode) renders the connect content directly on the
           panel (preview .connect has no wrapper card); the Account editor keeps
           its bordered row cards. -->
      <div v-for="(m,i) in editorRows" :key="i"
           :style="singleMode ? {} : { border: '1px solid var(--border)', borderRadius: '9px', padding: '10px', marginBottom: '8px', background: 'var(--surface-1)' }">

        <!-- Onboarding: two self-describing credential cards so the choice reads
             at a glance without extra copy. The compact toggle stays for the
             full (Account) editor's denser rows. -->
        <div v-if="singleMode" class="jv-ct">
          <div class="jv-ct-cards">
            <button v-for="opt in credTypes" :key="opt.value" type="button"
                    class="jv-ct-card" :class="{ on: m.credentialType===opt.value }"
                    @click="setCredType(m, opt.value)" :disabled="!editable"
                    :aria-pressed="m.credentialType===opt.value">
              <span class="jv-ct-ic">
                <svg v-if="opt.value==='api_key'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
                <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              </span>
              <span class="jv-ct-tx">
                <span class="jv-ct-t">{{ opt.label }}</span>
                <span class="jv-ct-d">{{ opt.desc }}</span>
              </span>
            </button>
          </div>
        </div>

        <!-- Row head: credential-type toggle (+ reorder/remove in Custom) -->
        <div v-if="!singleMode" style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
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

        <!-- API-key credential. Onboarding (singleMode) lays the four fields out as
             a 2×2 grid so this view's height sits close to the subscription view -
             no jarring resize when toggling. The Account editor keeps the dense row. -->
        <div v-if="m.credentialType!=='subscription'" :class="{ 'jv-single-body': singleMode }">
          <div v-if="singleMode" class="jv-ak-grid">
            <JvCombo :model-value="m.provider" @update:model-value="(v) => { m.provider = v; onProviderChange(m) }"
                     :options="providerOptions" :editable="editable" placeholder="Provider" />
            <JvCombo :model-value="m.model" @update:model-value="(v) => { m.model = v }" allow-custom
                     :options="modelSuggestionsForProvider(m.provider)" :editable="editable" placeholder="Model ID (e.g. gpt-4o)" />
            <input v-model="m.apiKey" :disabled="!editable" type="password"
                   :placeholder="m.hasKey ? 'key set, re-enter to change' : 'API key'" />
            <input v-model="m.baseUrl" :disabled="!editable" placeholder="Base URL (OpenAI-compatible)" />
          </div>
          <div v-else style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
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
                   :placeholder="m.hasKey ? 'key set, re-enter to change' : 'API key'"
                   style="flex:1.5;min-width:120px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
            <input v-model="m.baseUrl" :disabled="!editable" placeholder="Base URL (OpenAI-compatible)"
                   style="flex:1.5;min-width:120px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
          </div>
        </div>

        <!-- Chat-subscription credential. In the simplified (onboarding) editor
             the provider is enough: the Model ID field + rotation dropdown are
             hidden (model auto-defaults per provider), leaving just the provider
             picker + connect. The full account editor keeps all three. -->
        <div v-else :class="{ 'jv-single-body': singleMode }">
          <!-- Onboarding: labeled compact "Provider & model" select (preview
               .fieldlab + .sel-provider). Displays "Provider · model" - the model
               is auto-defaulted per provider (hidden field, see onUpstreamChange). -->
          <div v-if="singleMode" class="jv-pick">
            <div class="jv-fieldlab">Provider &amp; model</div>
            <JvCombo :model-value="m.upstream" @update:model-value="(v) => { m.upstream = v; onUpstreamChange(m) }"
                     :options="subUpstreamOpts(m)" :editable="editable" placeholder="Provider" />
          </div>
          <div v-else style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap;">
            <input v-model="m.model" :list="'jv-subdl-'+i" :disabled="!editable" placeholder="Model ID (e.g. gpt-5.5)"
                   style="flex:2;min-width:120px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;" />
            <datalist :id="'jv-subdl-'+i">
              <option v-for="s in (SUB_MODEL_SUGGESTIONS[m.upstream] || [])" :key="s" :value="s"></option>
            </datalist>
            <select v-model="m.upstream" @change="onUpstreamChange(m)" :disabled="!editable" title="Provider"
                    style="flex:1;min-width:100px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;">
              <option v-for="o in upstreamOpts" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
            <select v-model="m.rotation" :disabled="!editable" title="Account rotation"
                    style="flex:1.2;min-width:110px;padding:9px 12px;font-size:14px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-family:inherit;">
              <option v-for="o in rotationOpts" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </div>

          <!-- Connected accounts -->
          <div v-if="m.accounts && m.accounts.length" style="display:flex;flex-direction:column;gap:5px;margin-bottom:8px;">
            <div v-for="(a, ai) in m.accounts" :key="a.account_ref || ai" class="jv-status jv-status-ok">
              <span class="jv-status-ic"><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/></svg></span>
              <span class="jv-status-tx"><b>Connected</b> · {{ accountLabel(a) }}</span>
              <span class="jv-status-acts">
                <button v-if="editable && !singleMode" class="jv-status-act" @click="startConnect(m, ai)" title="Re-authorize to mint fresh tokens">Reconnect</button>
                <button v-if="editable" class="jv-status-act" @click="removeAccount(m, ai)">Disconnect</button>
              </span>
            </div>
          </div>
          <div v-else-if="!singleMode" style="font-size:13px;color:var(--text-3);margin-bottom:8px;">No accounts connected yet.</div>

          <!-- Onboarding: the two connect steps on a connected vertical spine
               (preview .csteps), always visible until an account is connected.
               Same handlers as the account editor's panel below: startConnect
               fetches the authorize URL (step 1's button turns into the real
               sign-in link), finishConnect submits the pasted callback URL. -->
          <template v-if="singleMode && !(m.accounts && m.accounts.length)">
            <div class="jv-cdivider"></div>
            <div class="jv-csteps">
              <div class="jv-cstep">
                <div class="jv-cnum">1</div>
                <div class="jv-cbody">
                  <div class="jv-ctit">Sign in with {{ m.upstream === 'google' ? 'Google' : 'OpenAI' }}</div>
                  <div class="jv-cdesc">Opens {{ m.upstream === 'google' ? 'Google' : 'OpenAI' }} in a new tab. Approve access, then come back here.</div>
                  <div class="jv-crow">
                    <template v-if="m._connect && m._connect.authorizeUrl">
                      <a :href="m._connect.authorizeUrl" target="_blank" rel="noopener noreferrer" class="jv-cbtn jv-cbtn-primary">Open sign-in ↗</a>
                      <button type="button" class="jv-cbtn jv-cbtn-ghost" @click="copyAuthorizeUrl(m)">{{ m._connect.copied ? 'Copied ✓' : 'Copy link' }}</button>
                    </template>
                    <button v-else type="button" class="jv-cbtn jv-cbtn-primary"
                            :disabled="!editable || (m._connect && m._connect.loading)" @click="startConnect(m)">
                      {{ m._connect && m._connect.loading ? 'Starting sign-in…' : 'Open sign-in ↗' }}
                    </button>
                  </div>
                </div>
              </div>
              <div class="jv-cstep" :class="{ 'jv-pending': !(m._connect && m._connect.authorizeUrl) }">
                <div class="jv-cnum">2</div>
                <div class="jv-cbody">
                  <div class="jv-ctit">Paste the callback URL</div>
                  <div class="jv-callout">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16h.01"/></svg>
                    <p>After you approve, the browser shows a <b>&ldquo;This site can&rsquo;t be reached&rdquo;</b> page. That&rsquo;s expected: copy the <b>full URL from the address bar</b> (<kbd>⌘/Ctrl</kbd>+<kbd>L</kbd>, then <kbd>⌘/Ctrl</kbd>+<kbd>C</kbd>) and paste it below.</p>
                  </div>
                  <input v-model="m._connect.pastedUrl" class="jv-paste" :disabled="!editable"
                         placeholder="http://localhost:1455/auth/callback?code=…" @keydown.enter="finishConnect(m)" />
                  <div v-if="m._connect && m._connect.authorizeUrl" class="jv-cacts">
                    <button type="button" class="jv-cbtn jv-cbtn-ghost" @click="closeConnect(m)">Cancel</button>
                    <button type="button" class="jv-cbtn jv-cbtn-primary" :disabled="m._connect.loading" @click="finishConnect(m)">
                      {{ m._connect.loading ? 'Connecting…' : 'Connect' }}
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="m._connect && m._connect.error" class="jv-cn-err">{{ m._connect.error }}</div>
          </template>

          <!-- Inline paste-back OAuth flow - two clear steps: open the sign-in
               (OAuth) URL, then paste the callback URL you're redirected to.
               (Account editor only; onboarding renders the spine above.) -->
          <div v-if="!singleMode && m._connect && m._connect.open" class="jv-cn">
            <div v-if="m._connect.authorizeUrl">
              <div class="jv-cn-step">
                <span class="jv-cn-num">1</span>
                <div class="jv-cn-body">
                  <div class="jv-cn-t">Sign in with your {{ m.upstream === 'google' ? 'Google' : 'OpenAI' }} account</div>
                  <div class="jv-cn-row">
                    <a :href="m._connect.authorizeUrl" target="_blank" rel="noopener noreferrer" class="jv-cn-open">Open sign-in ↗</a>
                    <button @click="copyAuthorizeUrl(m)" class="jv-cn-copy">{{ m._connect.copied ? 'Copied ✓' : 'Copy link' }}</button>
                  </div>
                </div>
              </div>
              <div class="jv-cn-step">
                <span class="jv-cn-num">2</span>
                <div class="jv-cn-body">
                  <div class="jv-cn-t">Paste the callback URL</div>
                  <div class="jv-cn-hint">After signing in you'll see a “This site can't be reached” page. Copy that page's full URL and paste it below.</div>
                  <input v-model="m._connect.pastedUrl" class="jv-cn-input" placeholder="http://localhost:1455/auth/callback?code=…" @keydown.enter="finishConnect(m)" />
                </div>
              </div>
              <div class="jv-cn-acts">
                <button @click="closeConnect(m)" class="jv-cn-cancel">Cancel</button>
                <button @click="finishConnect(m)" :disabled="m._connect.loading" class="jv-cn-connect">
                  {{ m._connect.loading ? 'Connecting…' : 'Connect' }}
                </button>
              </div>
            </div>
            <div v-else class="jv-cn-loading">Starting sign-in…</div>
            <div v-if="m._connect.error" class="jv-cn-err">{{ m._connect.error }}</div>
          </div>

          <!-- Account editor's connect entry point (onboarding's spine above owns
               startConnect there). -->
          <button v-if="editable && !singleMode && !(m._connect && m._connect.open)" @click="startConnect(m)"
                  :disabled="m._connect && m._connect.loading && !m._connect.authorizeUrl"
                  style="font-size:14px;font-weight:600;color:var(--surface);background:var(--blue);border:0;border-radius:8px;padding:11px 17px;cursor:pointer;">
            {{ (m.accounts && m.accounts.length) ? '+ Connect another account' : '+ Connect account' }}
          </button>
        </div>
      </div>

      <button v-if="isMulti && editable" @click="addModel"
              style="font-size:14px;color:var(--blue);background:transparent;border:1px dashed var(--border-2);border-radius:7px;padding:9px 16px;cursor:pointer;width:100%;">
        + Add model
      </button>
    </section>

    <!-- Save bar + sync status - hidden when a host renders its own footer. -->
    <div v-if="!footerless" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
      <button v-if="editable" @click="save" :disabled="saving || saveBlocked"
              :style="{padding:'12px 24px',background: saveBlocked ? 'var(--surface-3)' : 'var(--blue)',
                       color: saveBlocked ? 'var(--text-3)' : '#fff',border:'none',borderRadius:'9px',
                       cursor: saveBlocked ? 'not-allowed' : 'pointer',fontSize:'15px',fontWeight:'600'}">
        {{ saving ? 'Saving…' : 'Save configuration' }}
      </button>
      <span v-if="saveBlocked && missingVendors.length" style="font-size:13px;color:var(--amber);">
        Provide keys for: {{ missingVendors.map(providerLabel).join(', ') }}
      </span>
      <span v-else-if="dirty" style="font-size:13px;color:var(--amber);font-weight:600;">● Unsaved changes - Save configuration to apply</span>
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
import JvCombo from "@/components/JvCombo.vue"

const props = defineProps({
  editable: { type: Boolean, default: true },
  // Which setup tabs to expose. Default = the full 3-mode editor (Account page).
  // Onboarding passes ["quick"] to offer a single direct model and hide the
  // proxy-pool Preset/Custom tabs + the Direct/Proxy badge - faster signup, no
  // failover/pooling decisions up front (users configure that later in Account).
  modes: { type: Array, default: () => ["quick", "preset", "custom"] },
  // Hide the built-in Save bar so a host (onboarding) can render its own footer
  // and trigger save() via a template ref (exposed below).
  footerless: { type: Boolean, default: false },
})
const emit = defineEmits(["saved", "ready"])

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
const savedSnapshot = ref("__init__")  // savable pool as of last load/save; drives the unsaved-changes notice
let pollTimer = null

const ALL_MODE_TABS = [
  { value: "quick", label: "Quick" },
  { value: "preset", label: "Preset" },
  { value: "custom", label: "Custom" },
]
// Only the tabs the host allows, in canonical order.
const modeTabs = computed(() => ALL_MODE_TABS.filter((t) => props.modes.includes(t.value)))
// With a single allowed mode the tab bar + Direct/Proxy badge are just noise -
// hide them and render that mode's body directly (onboarding's quick-only editor).
const singleMode = computed(() => modeTabs.value.length <= 1)
// Whether any proxy-pool tab (Preset/Custom) is reachable - gates the Quick hint
// copy so it never points at tabs that aren't there.
const canPool = computed(() => props.modes.includes("preset") || props.modes.includes("custom"))
// Whether the single-mode (onboarding) row is savable - an account is connected,
// or an API key + provider/model are filled. Emitted so the host footer can
// invite the final "Onboard Jarvis" click once the user is ready.
const ready = computed(() => {
  if (!singleMode.value) return false
  const r = rows.value[0]
  if (!r) return false
  if (r.credentialType === "subscription") return (r.accounts || []).some((a) => a && (a.oauth_blob || a.account_ref))
  return !!((r.provider || "").trim() && (r.model || "").trim() && ((r.apiKey || "").trim() || r.hasKey))
})
const credTypes = [
  { value: "subscription", label: "Chat subscription", desc: "Sign in with your ChatGPT or Gemini plan" },
  { value: "api_key", label: "API key", desc: "Bring your own key from OpenAI, Anthropic and more" },
]
const rotationOpts = [
  { value: "sticky", label: "Sticky" },
  { value: "round_robin", label: "Round robin" },
  { value: "least_used", label: "Least used" },
]
const upstreamOpts = [
  { value: "openai", label: "OpenAI" },
  { value: "google", label: "Google Gemini" },
]
// Onboarding's compact "Provider & model" select shows "Provider · model"
// (preview .sel-provider, e.g. "OpenAI · gpt-5.5"). The active upstream shows
// the row's ACTUAL model id (a returning customer may have saved a non-default
// one); the other option previews the default onUpstreamChange would apply.
function subUpstreamOpts(m) {
  return upstreamOpts.map((o) => ({
    value: o.value,
    label: `${o.label} · ${(m.upstream === o.value && (m.model || "").trim()) || defaultSubscriptionModel(o.value)}`,
  }))
}
// Provider dropdown fed by the shared PROVIDER_LABELS (id⇄label). Rows store the
// display LABEL as `provider` (matches seedRowsFromConfig + the desk page).
const providerOptions = PROVIDER_LABELS.map((p) => p.label)

// ---- model-id suggestions (ported verbatim from jarvis_account.js) -------
const STATIC_MODEL_SUGGESTIONS = {
  "Anthropic": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"],
  "OpenAI": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-4o"],
  "Google Gemini": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-3.1-flash"],
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
// Quick renders only rows[0] and saving in Quick collapses the pool to that one
// model. When a real multi-model pool exists, lock the Quick tab so a stray click
// can't silently drop the other models - the user reduces the pool via Custom.
const quickLocked = computed(() => rows.value.length >= 2)
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

// Direct/Proxy badge - mirrors jarvis_account.js renderModeBadge().
// Quick is always Direct (single model); Preset is Proxy once chosen; Custom
// derives from the count of valid rows via the shared deriveMode helper.
// Valid (fillable) rows - shared by the badge mode + label. A subscription row
// needs a model id; an api_key row needs provider + model.
const validModels = computed(() => rows.value.filter((r) => r && (
  r.credentialType === "subscription" ? (r.model || "").trim() : ((r.provider || "").trim() && (r.model || "").trim())
)))
const badgeMode = computed(() => {
  // Quick is a single model: DIRECT for api_key, but a chat-subscription row
  // forces the cliproxy/proxy path (compute_proxy_active), so reflect that.
  if (llmMode.value === "quick") {
    const r0 = rows.value[0]
    return (r0 && r0.credentialType === "subscription") ? "proxy" : "direct"
  }
  if (llmMode.value === "preset") return selectedPreset.value ? "proxy" : "direct"
  return deriveMode(validModels.value, null)
})
// Human label. "failover" only makes sense with ≥2 models (a preset ladder or a
// multi-row custom pool). A lone chat subscription is still proxied (it needs
// the cliproxy sidecar) but has nothing to fail over to, so it reads plain
// "Proxy" rather than the misleading "Proxy (failover)".
const badgeLabel = computed(() => {
  // Only badge a real multi-model FAILOVER pool. A single model - a direct
  // api-key OR a lone chat subscription - shows NO badge: it was just noise, and
  // "Proxy" on a single subscription read as confusing/broken.
  if (llmMode.value === "preset") return selectedPreset.value ? "Proxy (failover)" : ""
  if (llmMode.value === "custom") return validModels.value.length >= 2 ? "Proxy (failover)" : ""
  return ""  // quick = single model
})
const syncLabel = computed(() => {
  if (sync.value.pending) return "Syncing to your agent…"
  const s = sync.value.last_sync_status || ""
  return s ? `Last sync: ${s}` : ""
})
// Unsaved-changes detector: current savable pool vs the last saved snapshot.
// Connecting an account mutates rows in memory (the fresh OAuth blob lives only
// here until saved), so this lights up the "Unsaved changes" notice.
const dirty = computed(() =>
  savedSnapshot.value !== "__init__" && !saving.value && poolSnapshot() !== savedSnapshot.value
)

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
    // Onboarding hides the model field - default it from the chosen provider so
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
// provider-specific - otherwise we'd save a model bound to the wrong provider's
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
  // Simplified editor hides the model field - make sure a subscription row always
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
    const provider = m.upstream === "google" ? "Google Gemini" : "OpenAI"
    const res = await api.beginPoolAccountSignin(provider, m.model.trim())
    // Backend returns an envelope: {ok:true, data:{nonce, authorize_url, …}} or
    // {ok:false, error:{code, message}}. Unwrap data; surface errors instead of
    // hanging on "Starting sign-in…".
    if (!res || res.ok === false) {
      m._connect.loading = false
      m._connect.error = (res && res.error && res.error.message) || "Couldn't start sign-in. Try again."
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
    // Same {ok, data} envelope as begin - unwrap + surface errors.
    if (!res || res.ok === false) {
      m._connect.loading = false
      m._connect.error = (res && res.error && res.error.message) || "Couldn't connect the account. Check the pasted URL and try again."
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
    if (ri != null && ri >= 0 && ri < m.accounts.length) {
      m.accounts.splice(ri, 1, acct)
      // Reconnecting one slot but signing in as an account already held by a
      // DIFFERENT slot would leave two identical accounts - drop the duplicate.
      if (byEmail >= 0 && byEmail !== ri) m.accounts.splice(byEmail, 1)
    } else if (byEmail >= 0) m.accounts.splice(byEmail, 1, acct)
    else m.accounts.push(acct)
    m._connect = blankConnect()
    // The just-minted OAuth blob lives only in memory until the pool is saved, so
    // navigating off the page would orphan this account. In the account editor,
    // persist immediately; if the pool isn't valid yet, save() surfaces the reason
    // and the "Unsaved changes" notice stays up so nothing is silently lost. Skip
    // in the footerless onboarding editor - there the host's CTA drives save.
    if (!props.footerless) await save()
  } catch (e) { m._connect.loading = false; m._connect.error = _err(e) }
}
function closeConnect(m) { m._connect = blankConnect() }
function copyAuthorizeUrl(m) {
  const url = m._connect && m._connect.authorizeUrl
  if (!url) return
  copyTextWithFallback(url).then(() => {
    m._connect.copied = true
    setTimeout(() => { if (m._connect) m._connect.copied = false }, 1400)
  }).catch(() => { m._connect.error = "Could not copy. Select the URL above and copy manually." })
}

// ---- load / save ---------------------------------------------------------
// Seed the canonical rows from get_llm_config, then augment each with the
// transient UI-only fields the editor needs (upstream + _connect). Seeded
// accounts carry no oauth_blob (never returned by the server) - reconnect to
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
    // Onboarding is quick-only (singleMode): the editor shows a single editable
    // row (editorRows renders rows[0]) but we KEEP any seeded tail rows so a
    // returning customer's existing failover pool round-trips through save()
    // instead of being silently dropped. Only the preset (which quick can't
    // represent) is cleared.
    if (singleMode.value) {
      llmMode.value = props.modes[0] || "quick"
      selectedPreset.value = ""
      if (!rows.value.length) rows.value = [newRow()]
      // Onboarding default = Chat subscription (the common path). Only flip a
      // pristine row so a returning customer's saved API-key setup is preserved.
      const r0 = rows.value[0]
      if (r0 && r0.credentialType === "api_key" && !(r0.model || "").trim() &&
          !(r0.apiKey || "").trim() && !r0.hasKey && !(r0.accounts && r0.accounts.length)) {
        setCredType(r0, "subscription")
      }
    } else if (!props.modes.includes(llmMode.value)) {
      llmMode.value = props.modes[0] || "quick"
      selectedPreset.value = ""
      if (!rows.value.length) rows.value = [newRow()]
    }
    // Baseline for the unsaved-changes notice - the pool as just loaded is clean.
    savedSnapshot.value = poolSnapshot()
  } catch (e) { err.value = _err(e) }
  try { sync.value = (await api.getLlmSyncStatus()) || sync.value } catch (e) { /* non-fatal */ }
  try { catalog.value = (await api.getPresetCatalog()) || [] } catch (e) { /* backend bundled fallback */ }
}

// Stable string of the savable pool + preset - the cheap key the dirty-notice
// and snapshot reset compare against.
function poolSnapshot() {
  try { return JSON.stringify({ m: buildSaveModels(rows.value), p: selectedPreset.value }) }
  catch (e) { return "" }
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
    // Exception: onboarding's singleMode keeps seeded tail rows (editorRows only
    // renders the first) so a returning customer's existing pool isn't dropped.
    saveModels = buildSaveModels(llmMode.value === "quick" && !singleMode.value ? rows.value.slice(0, 1) : rows.value)
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

// Tell the host (onboarding footer) when the config becomes savable so it can
// highlight the "Onboard Jarvis" CTA.
watch(ready, (v) => emit("ready", v), { immediate: true })

onMounted(load)
onBeforeUnmount(stopPolling)

// Let a host (onboarding, footerless) drive Save from its own footer.
defineExpose({ save })
</script>

<style scoped>
/* Onboarding method cards (preview .method/.m-opt): sel = blue border + 3px
   ring; icon tile flips from neutral to blue tint when selected. Preview's
   --accent maps to the app's --blue (and -bg/-bd). */
.jv-ct { margin-bottom: 20px; }
.jv-ct-cards { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.jv-ct-card {
  display: flex; align-items: flex-start; gap: 12px; text-align: left;
  padding: 15px 16px; border: 1.5px solid var(--border); border-radius: 12px;
  background: var(--surface); cursor: pointer; font: inherit; color: var(--text);
  transition: border-color .15s, box-shadow .15s;
}
.jv-ct-card.on { border-color: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-ct-card:disabled { cursor: default; }
.jv-ct-ic {
  flex: none; width: 34px; height: 34px; border-radius: 9px;
  display: grid; place-items: center;
  background: var(--surface-2); border: 1px solid var(--border); color: var(--text-2);
}
.jv-ct-card.on .jv-ct-ic { background: var(--blue-bg); border-color: var(--blue-bd); color: var(--blue); }
.jv-ct-ic svg { width: 17px; height: 17px; stroke-width: 1.8; }
.jv-ct-tx { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.jv-ct-t { font-size: 13.5px; font-weight: 600; }
.jv-ct-d { font-size: 12px; color: var(--text-3); line-height: 1.4; }
/* Labeled compact "Provider & model" select (preview .fieldlab/.sel-provider):
   40px field, 10px radius, border-2 border, same 3px focus ring as the rest of
   the wizard's inputs. */
.jv-fieldlab { font-size: 12px; font-weight: 550; color: var(--text-2); margin-bottom: 6px; }
.jv-pick :deep(.jvc-field) {
  min-height: 40px; padding: 0 14px;
  border-color: var(--border-2); border-radius: 10px; font-size: 13.5px;
  transition: border-color .15s, box-shadow .15s;
}
.jv-pick :deep(.jvc-field:hover) { border-color: var(--border-2); }
.jv-pick :deep(.jvc-field:focus-within),
.jv-pick :deep(.jvc-field.jvc-open) { border-color: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
/* The two connect steps on a connected vertical spine (preview .csteps): no
   shade boxes, a 1.5px line joins the numbered dots; step 2 reads pending
   (neutral dot) until the sign-in URL exists. */
.jv-cdivider { height: 1px; background: var(--border); margin: 20px 0 18px; }
.jv-cstep { position: relative; display: flex; gap: 14px; padding: 2px 0 22px; }
.jv-cstep:last-child { padding-bottom: 4px; }
.jv-cstep:not(:last-child)::before { content: ""; position: absolute; left: 12.5px; top: 32px; bottom: 4px; width: 1.5px; background: var(--border); }
.jv-cnum {
  width: 26px; height: 26px; border-radius: 50%; box-sizing: border-box;
  background: var(--blue); color: #fff;
  display: grid; place-items: center; font-size: 12.5px; font-weight: 600;
  flex: none; position: relative; z-index: 1;
}
.jv-cstep.jv-pending .jv-cnum { background: var(--surface-2); color: var(--text-3); border: 1.5px solid var(--border-2); }
.jv-cbody { flex: 1; min-width: 0; }
.jv-ctit { font-size: 13.5px; font-weight: 600; margin-bottom: 3px; }
.jv-cdesc { font-size: 12.5px; color: var(--text-3); line-height: 1.45; margin-bottom: 11px; }
.jv-crow { display: flex; gap: 9px; flex-wrap: wrap; }
/* Small in-step buttons (preview .btn--sm on .btn--primary/.btn--ghost). */
.jv-cbtn {
  display: inline-flex; align-items: center; justify-content: center; gap: 7px;
  height: 34px; padding: 0 13px; border-radius: 9px;
  border: 1px solid transparent;
  font-family: inherit; font-size: 12.5px; font-weight: 600; line-height: 1;
  cursor: pointer; white-space: nowrap; text-decoration: none;
  transition: transform .12s, box-shadow .15s, background .15s, border-color .15s;
}
.jv-cbtn:active { transform: scale(.98); }
/* The Open sign-in control is an <a>, which the wizard's button-scoped
   focus-visible rule misses - give both spine controls their own outline. */
.jv-cbtn:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.jv-cbtn:disabled { opacity: .55; cursor: default; transform: none; }
.jv-cbtn-primary { background: var(--blue); color: #fff; box-shadow: 0 2px 10px rgba(20, 20, 30, .16); }
.jv-cbtn-primary:hover:not(:disabled) { color: #fff; transform: translateY(-1px); box-shadow: 0 8px 22px rgba(20, 20, 30, .22); }
.jv-cbtn-ghost { background: var(--surface); border-color: var(--border-2); color: var(--text-2); }
.jv-cbtn-ghost:hover:not(:disabled) { background: var(--surface-2); color: var(--text); border-color: var(--border); }
/* ONE amber callout: the "This site can't be reached is expected" guidance with
   the inline kbd shortcut hint (preview .callout). */
.jv-callout {
  display: flex; gap: 9px; align-items: flex-start;
  background: var(--amber-bg); border: 1px solid var(--amber-bd);
  border-radius: 9px; padding: 9px 12px; margin-bottom: 10px;
}
.jv-callout svg { color: var(--amber); flex: none; margin-top: 1px; }
.jv-callout p { margin: 0; font-size: 12px; color: var(--text-2); line-height: 1.5; }
.jv-callout b { color: var(--text); font-weight: 600; }
.jv-callout kbd {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 10px; background: var(--surface);
  border: 1px solid var(--amber-bd); border-radius: 4px; padding: 0 4px;
}
/* Dashed mono paste input; focus solidifies the border + shows the wizard's
   3px ring (preview .paste). */
.jv-paste {
  width: 100%; height: 44px; box-sizing: border-box;
  border: 1.5px dashed var(--border-2); border-radius: 11px;
  background: var(--surface-1); padding: 0 14px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px; color: var(--text);
  transition: border-color .15s, background .15s;
}
.jv-paste::placeholder { color: var(--text-3); }
.jv-paste:focus { outline: none; border-style: solid; border-color: var(--blue); background: var(--surface); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-paste:disabled { opacity: .55; }
.jv-cacts { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
/* Clean status pill - connected (ok) / failed (bad). Reused by the subscription
   connected row and (later) the API-key verify result. No red ✕ - a subtle text
   action handles disconnect. */
.jv-status { display: flex; align-items: center; gap: 9px; padding: 10px 12px; border-radius: 9px; font-size: 13.5px; margin-bottom: 8px; }
.jv-status-ok { border: 1px solid var(--green-bd); background: var(--green-bg); }
.jv-status-bad { border: 1px solid var(--red-bd); background: var(--red-bg); }
.jv-status-ic { flex: none; display: flex; color: var(--green); }
.jv-status-bad .jv-status-ic { color: var(--red); }
.jv-status-tx { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
.jv-status-tx b { color: var(--green); font-weight: 600; }
.jv-status-bad .jv-status-tx b { color: var(--red); }
.jv-status-acts { margin-left: auto; display: flex; gap: 12px; flex: none; }
.jv-status-act { background: transparent; border: 0; color: var(--text-3); font-size: 12.5px; cursor: pointer; padding: 0; }
.jv-status-act:hover { color: var(--text); text-decoration: underline; text-underline-offset: 2px; }
/* Paste-back OAuth connect panel - two numbered steps (open sign-in URL / paste
   the callback URL), styled to match the rest of the onboarding editor. */
.jv-cn { margin-top: 8px; padding: 15px; background: var(--surface-1); border: 1px solid var(--border); border-radius: 11px; }
.jv-cn-step { display: flex; gap: 10px; margin-bottom: 13px; }
.jv-cn-num { flex: none; width: 21px; height: 21px; border-radius: 50%; background: var(--blue); color: var(--surface); font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center; margin-top: 1px; }
.jv-cn-body { flex: 1; min-width: 0; }
.jv-cn-t { font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 7px; }
.jv-cn-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.jv-cn-open { font-size: 13px; font-weight: 600; color: var(--surface); text-decoration: none; padding: 8px 14px; border: 0; background: var(--blue); border-radius: 8px; }
.jv-cn-copy { font-size: 12.5px; padding: 7px 12px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; background: var(--surface); color: var(--text-2); }
.jv-cn-copy:hover { color: var(--text); }
.jv-cn-hint { font-size: 12px; color: var(--text-3); line-height: 1.5; margin-bottom: 8px; }
.jv-cn-input { width: 100%; padding: 9px 12px; font-size: 13.5px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); color: var(--text); font-family: inherit; box-sizing: border-box; }
.jv-cn-input:focus { outline: none; border-color: var(--blue-bd); }
.jv-cn-acts { display: flex; justify-content: flex-end; gap: 8px; }
.jv-cn-cancel { padding: 8px 15px; font-size: 13px; border: 1px solid var(--border); border-radius: 8px; cursor: pointer; background: var(--surface); color: var(--text-2); }
.jv-cn-connect { padding: 8px 17px; font-size: 13px; font-weight: 600; border: 0; border-radius: 8px; cursor: pointer; background: var(--blue); color: var(--surface); }
.jv-cn-connect:disabled { opacity: .6; cursor: not-allowed; }
.jv-cn-loading { font-size: 13px; color: var(--text-2); }
.jv-cn-err { margin-top: 9px; font-size: 13px; color: var(--red); }
/* Lock both credential modes to the same body height in onboarding so toggling
   API key ↔ Chat subscription never resizes the card (first-impression polish). */
.jv-single-body { min-height: 96px; }
/* API-key fields as a 2×2 grid in onboarding - keeps this view's height close to
   the subscription view so toggling doesn't resize the card. Fields match the
   wizard's inputs (42px, 10px radius, border-2, 3px focus ring). */
.jv-ak-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.jv-ak-grid input {
  width: 100%; height: 42px; padding: 0 13px; font-size: 13.5px;
  border: 1px solid var(--border-2); border-radius: 10px;
  background: var(--surface); color: var(--text); font-family: inherit; box-sizing: border-box;
}
.jv-ak-grid input::placeholder { color: var(--text-3); }
.jv-ak-grid input:focus { outline: none; border-color: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-ak-grid :deep(.jvc-field) {
  min-height: 42px; padding: 0 13px;
  border-color: var(--border-2); border-radius: 10px; font-size: 13.5px;
  transition: border-color .15s, box-shadow .15s;
}
.jv-ak-grid :deep(.jvc-field:hover) { border-color: var(--border-2); }
.jv-ak-grid :deep(.jvc-field:focus-within),
.jv-ak-grid :deep(.jvc-field.jvc-open) { border-color: var(--blue); box-shadow: 0 0 0 3px var(--blue-bg); }
.jv-ak-grid :deep(.jvc-input::placeholder) { color: var(--text-3); }
/* Preview stacks .method at 820px - the same breakpoint as the wizard's other grids. */
@media (max-width: 820px) { .jv-ct-cards, .jv-ak-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) {
  .jv-ct-card, .jv-cbtn, .jv-paste,
  .jv-pick :deep(.jvc-field), .jv-ak-grid :deep(.jvc-field) { transition: none; }
}
</style>
