<template>
  <!-- Reusable LLM-pool editor. Renders the 3-mode SETUP UI (Quick | Preset |
       Custom) over the unified proxy-pool model and persists via saveLlmPool.
       Self-loads its config on mount (seeded through seedRowsFromConfig into the
       canonical camelCase row shape). Expects an ancestor to supply the theme
       CSS vars (--surface, --text, …); uses only tokens, no hard-coded colors.
       Consumers: AiView (manage tab) now, AccountView + onboarding later. -->
  <div class="jv-llm-editor" style="font-family:inherit;color:var(--text);">
    <div v-if="err" style="color:var(--red);font-size:13px;margin-bottom:12px;">{{ err }}</div>

    <!-- ============================================================
         UNIFIED FAILOVER LIST + CONFIG SECTION (!singleMode only - the
         Account/Settings editor). Onboarding never reaches this branch
         (singleMode forces llmMode==='quick' below). Phase 1: read list
         only; config section arrives in phase 2. ============================================================ -->
    <section v-if="!singleMode" style="margin-bottom:18px;">
      <!-- No section heading and no explainer here: the dialog already titles this
           pane ("AI models" / "The AI connection that powers Jarvis."), so an
           uppercase "AI MODELS" repeated below it was pure duplication. The failover
           behaviour is surfaced where it's actionable instead: on the "No backup yet"
           card, which self-hides once a second model exists.
           The badge stays - it only appears for a real multi-model failover pool. -->
      <div v-if="badgeLabel" style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap;">
        <span style="font-size:12px;font-weight:600;padding:4px 11px;border-radius:20px;background:var(--green-bg);color:var(--green);">
          {{ badgeLabel }}
        </span>
      </div>

      <!-- Legacy DIRECT chat-subscription (flat-field OAuth, no proxy) - not
           part of rows.value/the failover pool, so no order badge/reorder. -->
      <div v-if="showDirectRow" class="jv-flist-row">
        <span class="jv-flist-chip">Direct</span>
        <span class="jv-flist-model">{{ directStatus.model || directStatus.provider || 'Chat subscription' }}</span>
        <span v-if="directStatus.account_email" style="font-size:11px;color:var(--text-3);">{{ directStatus.account_email }}</span>
        <span class="jv-pool-dot jv-pool-dot--ok" aria-hidden="true"></span>
        <span class="jv-flist-acts">
          <button v-if="editable" @click="directPanelOpen = !directPanelOpen" class="jv-btn jv-btn--sm jv-btn--ghost">{{ directPanelOpen ? 'Close' : 'Reconnect' }}</button>
          <button v-if="editable" @click="removeDirect" class="jv-btn jv-btn--sm jv-btn--ghost jv-pool-disc">Remove</button>
        </span>
      </div>
      <div v-if="showDirectRow && directPanelOpen" class="jv-cfgpanel">
        <DirectSubscriptionCard :status="directStatus" :editable="editable" @reauthorized="onDirectCardChanged" @disconnected="onDirectCardChanged" />
      </div>

      <div v-if="!rows.length && !showDirectRow" style="font-size:13px;color:var(--text-3);padding:8px 0;">No models yet. Add one below.</div>

      <div v-for="(row, i) in rows" :key="i" class="jv-flist-row">
        <span class="jv-pool-badge">{{ i + 1 }}</span>
        <span class="jv-flist-chip">{{ sourceChip(row) }}</span>
        <span class="jv-flist-model" :class="{ 'jv-flist-model--unset': !row.model }">{{ rowModelLabel(row) }}</span>
        <span v-if="row.credentialType!=='subscription' && row.hasKey" style="font-size:11px;color:var(--text-3);">key set</span>
        <span class="jv-pool-dot" :class="'jv-pool-dot--' + accountHealth(row).level" aria-hidden="true"></span>
        <span v-if="accountHealth(row).label" class="jv-pool-acct-health" :class="'jv-pool-acct-health--' + accountHealth(row).level" :title="accountHealth(row).title">{{ accountHealth(row).label }}</span>
        <!-- Reorder + [Edit][Reconnect|Replace key][Remove], always right-aligned. -->
        <span class="jv-flist-acts">
          <button @click="move(i,-1)" :disabled="!editable || i===0" title="Up" class="jv-pool-iconbtn">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 15l-6-6-6 6"/></svg>
          </button>
          <button @click="move(i,1)" :disabled="!editable || i===rows.length-1" title="Down" class="jv-pool-iconbtn">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>
          </button>
          <button v-if="editable" @click="openEdit(i)" class="jv-btn jv-btn--sm jv-btn--ghost">Edit</button>
          <button v-if="editable && row.credentialType==='subscription'" @click="quickReconnect(i)" class="jv-btn jv-btn--sm jv-btn--ghost">Reconnect</button>
          <button v-else-if="editable" @click="openEdit(i)" class="jv-btn jv-btn--sm jv-btn--ghost">Replace key</button>
          <button v-if="editable" @click="remove(i)" class="jv-btn jv-btn--sm jv-btn--ghost jv-pool-disc">Remove</button>
        </span>
      </div>

      <!-- Dashed add-row rather than a small solid button: it reads as "the next
           row goes here", fills the column, and matches the add affordances used
           elsewhere in the product (New skill / Drop a file). -->
      <button v-if="editable && !panel.open" @click="openAdd" class="jv-flist-add">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14" /></svg>
        Add a model
      </button>

      <!-- A single model has nothing to fall back to. Name the consequence instead
           of leaving the customer to infer it from "tried in order". -->
      <div v-if="editable && !panel.open && rows.length === 1 && !showDirectRow" class="jv-flist-hint">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 16v-4M12 8h.01" /></svg>
        <span><b>No backup yet.</b> If this model fails or hits its limit, chat stops.
        Add a second one and Jarvis switches over automatically.</span>
      </div>

      <!-- Master-detail config section: Add/Edit a single row, or (add-mode
           only) apply a preset that replaces the whole pool. Field markup +
           connect flow are reused verbatim from the account editor's former
           per-row layout; only the panel container is new. -->
      <div v-if="panel.open" class="jv-cfgpanel">
        <div class="jv-cfgpanel-head">
          <div class="jv-cfgpanel-title">{{ panel.mode === 'add' ? 'Add a model' : 'Edit model' }}</div>
        </div>

        <div class="jv-pool-segct" role="group" aria-label="Source" style="margin-bottom:12px;">
          <button type="button" class="jv-pool-segbtn" :class="{ on: panel.source==='subscription' }"
                  :disabled="!editable" @click="setPanelSource('subscription')">Chat subscription</button>
          <button type="button" class="jv-pool-segbtn" :class="{ on: panel.source==='api_key' }"
                  :disabled="!editable" @click="setPanelSource('api_key')">API key</button>
          <!-- Presets are NOT shipping yet: shown but disabled, so the capability is
               discoverable without being clickable. Keep setPanelSource('preset')
               and the preset branch below intact - re-enabling is just dropping the
               `disabled` and the tag. -->
          <button v-if="panel.mode==='add'" type="button" class="jv-pool-segbtn jv-pool-segbtn--soon"
                  disabled title="Coming soon">From a preset<span class="jv-soon">Soon</span></button>
        </div>

        <!-- API-key source -->
        <div v-if="panel.source==='api_key' && panelRow">
          <!-- 2x2 grid, not four fields crammed across one row: the flex ratios
               (1 / 1.5 / 1.5 / 1.5) produced four different widths and read as
               noise. Provider first, since it decides the model suggestions. -->
          <div class="jv-cfg-grid">
            <div class="jv-pool-field">
              <label class="jv-pool-lab">Provider</label>
              <select v-model="panelRow.provider" @change="onProviderChange(panelRow)" :disabled="!editable" title="Provider" class="jv-cfg-inp">
                <option v-for="p in providerOptions" :key="p" :value="p">{{ p }}</option>
              </select>
            </div>
            <div class="jv-pool-field">
              <label class="jv-pool-lab">Model</label>
              <input v-model="panelRow.model" list="jv-cfg-dl" :disabled="!editable" placeholder="Model ID (e.g. gpt-4o)" class="jv-cfg-inp" />
              <datalist id="jv-cfg-dl">
                <option v-for="s in modelSuggestionsForProvider(panelRow.provider)" :key="s" :value="s"></option>
              </datalist>
            </div>
            <div class="jv-pool-field">
              <label class="jv-pool-lab">API key</label>
              <input v-model="panelRow.apiKey" :disabled="!editable" type="password"
                     :placeholder="panelRow.hasKey ? 'key set, re-enter to change' : 'API key'" class="jv-cfg-inp" />
            </div>
            <div class="jv-pool-field">
              <label class="jv-pool-lab">Base URL <span class="jv-pool-opt">(optional)</span></label>
              <input v-model="panelRow.baseUrl" :disabled="!editable" placeholder="Base URL (OpenAI-compatible)" class="jv-cfg-inp" />
            </div>
          </div>
          <!-- Resilient-by-default (API KEYS ONLY): expands this provider into
               its full single-vendor failover chain on close, sharing the
               same key. Add-mode only. -->
          <label v-if="panel.mode==='add'" style="display:flex;align-items:center;gap:8px;margin-top:11px;font-size:13px;color:var(--text-2);cursor:pointer;">
            <input type="checkbox" v-model="panel.addBackups" :disabled="!editable" />
            Add backup models automatically (recommended)
          </label>
        </div>

        <!-- Chat-subscription source -->
        <div v-else-if="panel.source==='subscription' && panelRow">
          <!-- Provider is the ONLY field for a chat subscription. There is no model
               picker: a plan grants you its model, so asking a customer to type a
               model id was busywork and an easy way to enter an invalid one. The id
               is derived from the provider (setCredType / onUpstreamChange), which
               validatePool + save still require. Onboarding already worked this way;
               the settings editor now matches it.
               Account rotation is likewise not exposed - it only matters once one
               provider has several accounts, and defaults to "sticky" in the schema. -->
          <div class="jv-cfg-grid" style="margin-bottom:10px;">
            <div class="jv-pool-field">
              <label class="jv-pool-lab">Provider</label>
              <select v-model="panelRow.upstream" @change="onUpstreamChange(panelRow)" :disabled="!editable" title="Provider" class="jv-cfg-inp">
                <option v-for="o in upstreamOpts" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </div>
          </div>

          <!-- Connected accounts (markup reused verbatim from the former
               per-row layout). -->
          <div v-if="panelRow.accounts && panelRow.accounts.length" class="jv-pool-accts">
            <div class="jv-pool-lab">Connected accounts ({{ panelRow.accounts.length }})</div>
            <div class="jv-pool-acctlist">
              <div v-for="(a, ai) in panelRow.accounts" :key="a.account_ref || ai" class="jv-pool-acctchip">
                <span class="jv-pool-avatar">{{ (accountLabel(a) || '?').charAt(0).toUpperCase() }}</span>
                <span class="jv-pool-accttx">{{ accountLabel(a) }}</span>
                <span class="jv-pool-dot" :class="'jv-pool-dot--' + accountHealth(panelRow).level" aria-hidden="true"></span>
                <span v-if="accountHealth(panelRow).label" class="jv-pool-acct-health" :class="'jv-pool-acct-health--' + accountHealth(panelRow).level" :title="accountHealth(panelRow).title">{{ accountHealth(panelRow).label }}</span>
                <span class="jv-pool-acctacts">
                  <button v-if="editable" class="jv-btn jv-btn--sm jv-btn--ghost" @click="startConnect(panelRow, ai)" title="Re-authorize to mint fresh tokens">Reconnect</button>
                  <button v-if="editable" class="jv-btn jv-btn--sm jv-btn--ghost jv-pool-disc" @click="removeAccount(panelRow, ai)">Disconnect</button>
                </span>
              </div>
              <button v-if="editable && !(panelRow._connect && panelRow._connect.open)" @click="startConnect(panelRow)"
                      :disabled="panelRow._connect && panelRow._connect.loading && !panelRow._connect.authorizeUrl"
                      class="jv-pool-addrow">
                + Add account
              </button>
            </div>
          </div>
          <div v-else style="font-size:13px;color:var(--text-3);margin-bottom:8px;">No accounts connected yet.</div>

          <!-- Paste-back OAuth connect panel (reused verbatim). -->
          <div v-if="panelRow._connect && panelRow._connect.open" class="jv-cn">
            <div v-if="panelRow._connect.authorizeUrl">
              <div class="jv-cn-step">
                <span class="jv-cn-num">1</span>
                <div class="jv-cn-body">
                  <div class="jv-cn-t">Sign in with your {{ panelRow.upstream === 'google' ? 'Google' : 'OpenAI' }} account</div>
                  <div class="jv-cn-row">
                    <a :href="panelRow._connect.authorizeUrl" target="_blank" rel="noopener noreferrer" class="jv-cn-open">Open sign-in ↗</a>
                    <button @click="copyAuthorizeUrl(panelRow)" class="jv-cn-copy">{{ panelRow._connect.copied ? 'Copied ✓' : 'Copy link' }}</button>
                  </div>
                </div>
              </div>
              <div class="jv-cn-step">
                <span class="jv-cn-num">2</span>
                <div class="jv-cn-body">
                  <div class="jv-cn-t">Paste the callback URL</div>
                  <div class="jv-cn-hint">After signing in you'll see a “This site can't be reached” page. Copy that page's full URL and paste it below.</div>
                  <input v-model="panelRow._connect.pastedUrl" class="jv-cn-input" placeholder="http://localhost:1455/auth/callback?code=…" @keydown.enter="finishConnect(panelRow)" />
                </div>
              </div>
              <div class="jv-cn-acts">
                <button @click="closeConnect(panelRow)" class="jv-cn-cancel">Cancel</button>
                <button @click="finishConnect(panelRow)" :disabled="panelRow._connect.loading" class="jv-cn-connect">
                  {{ panelRow._connect.loading ? 'Connecting…' : 'Connect' }}
                </button>
              </div>
            </div>
            <div v-else class="jv-cn-loading">Starting sign-in…</div>
            <div v-if="panelRow._connect.error" class="jv-cn-err">{{ panelRow._connect.error }}</div>
          </div>

          <button v-if="editable && !(panelRow._connect && panelRow._connect.open) && !(panelRow.accounts && panelRow.accounts.length)"
                  @click="startConnect(panelRow)"
                  :disabled="panelRow._connect && panelRow._connect.loading && !panelRow._connect.authorizeUrl"
                  class="jv-btn jv-btn--sm jv-btn--primary">
            + Connect account
          </button>
        </div>

        <!-- From a preset (add-mode only) - picking a card replaces the whole
             pool, same as the account editor's former Preset tab, just
             relocated here (selectPreset/missingVendors/saveBlocked reused
             verbatim). -->
        <div v-else-if="panel.source==='preset'">
          <p v-if="!catalog.length" style="font-size:14px;color:var(--text-3);margin:0 0 12px;">
            Couldn't load presets. Use <b>Chat subscription</b> or <b>API key</b>.
          </p>
          <div v-else style="max-height:360px;overflow-y:auto;padding-right:4px;">
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
        </div>

        <div class="jv-cfgpanel-acts">
          <button type="button" class="jv-btn jv-btn--sm jv-btn--ghost" @click="closePanel">
            {{ panel.source==='preset' ? 'Done' : (panel.mode==='add' ? 'Cancel' : 'Close') }}
          </button>
        </div>
      </div>
    </section>

    <!-- ================ QUICK / CUSTOM (shared rows) ================ -->
    <section v-if="singleMode" style="margin-bottom:18px;">
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
        </div>

        <!-- Chat-subscription credential. In the simplified (onboarding) editor
             the provider is enough: the Model ID field + rotation dropdown are
             hidden (model auto-defaults per provider), leaving just the provider
             picker + connect. The full account editor keeps all three. -->
        <div v-else :class="{ 'jv-single-body': singleMode }">
          <!-- Onboarding: just a Provider select. A chat subscription runs one
               fixed model per provider (auto-defaulted per onUpstreamChange /
               startConnect), so the model is not a user choice here - it is set
               behind the scenes and editable later in Settings → Account. -->
          <div v-if="singleMode" class="jv-pick">
            <div class="jv-fieldlab">Provider</div>
            <!-- Same-value guard: onUpstreamChange drops connected accounts (they
                 are provider-specific), so reselecting the CURRENT provider must
                 be a no-op rather than wiping a finished OAuth connect. -->
            <JvCombo :model-value="m.upstream" @update:model-value="(v) => { if (v === m.upstream) return; m.upstream = v; onUpstreamChange(m) }"
                     :options="upstreamOpts" :editable="editable" placeholder="Provider" />
          </div>

          <!-- Connected accounts -->
          <div v-if="m.accounts && m.accounts.length" class="jv-pool-accts">
            <div class="jv-pool-lab">Connected accounts ({{ m.accounts.length }})</div>
            <div class="jv-pool-acctlist">
              <div v-for="(a, ai) in m.accounts" :key="a.account_ref || ai" class="jv-pool-acctchip">
                <span class="jv-pool-avatar">{{ (accountLabel(a) || '?').charAt(0).toUpperCase() }}</span>
                <span class="jv-pool-accttx">{{ accountLabel(a) }}</span>
                <span class="jv-pool-dot" :class="'jv-pool-dot--' + accountHealth(m).level" aria-hidden="true"></span>
                <span v-if="accountHealth(m).label" class="jv-pool-acct-health" :class="'jv-pool-acct-health--' + accountHealth(m).level" :title="accountHealth(m).title">{{ accountHealth(m).label }}</span>
                <span class="jv-pool-acctacts">
                  <button v-if="editable && !singleMode" class="jv-btn jv-btn--sm jv-btn--ghost" @click="startConnect(m, ai)" title="Re-authorize to mint fresh tokens">Reconnect</button>
                  <button v-if="editable" class="jv-btn jv-btn--sm jv-btn--ghost jv-pool-disc" @click="removeAccount(m, ai)">Disconnect</button>
                </span>
              </div>
              <button v-if="editable && !singleMode && !(m._connect && m._connect.open)" @click="startConnect(m)"
                      :disabled="m._connect && m._connect.loading && !m._connect.authorizeUrl"
                      class="jv-pool-addrow">
                + Add account
              </button>
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
                  <div class="jv-chead">
                    <div class="jv-ctit">Sign in with {{ m.upstream === 'google' ? 'Google' : 'OpenAI' }}</div>
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
                  <div class="jv-cdesc">Opens {{ m.upstream === 'google' ? 'Google' : 'OpenAI' }} in a new tab. Approve access, then come back here.</div>
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
                  <!-- Disabled until step 1 minted an authorize URL: a URL pasted
                       before sign-in has no nonce to pair with (finishConnect
                       would no-op), a silent dead-end. -->
                  <input v-model="m._connect.pastedUrl" class="jv-paste"
                         :disabled="!editable || !(m._connect && m._connect.authorizeUrl)"
                         :placeholder="m._connect && m._connect.authorizeUrl
                           ? 'http://localhost:1455/auth/callback?code=…'
                           : 'Complete step 1 first, then paste the URL here'"
                         @keydown.enter="finishConnect(m)" />
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

        </div>
      </div>

      <button v-if="isMulti && editable" @click="addModel" class="jv-btn jv-btn--sm jv-btn--ghost">
        + Add model
      </button>
    </section>

    <!-- Save bar + sync status - hidden when a host renders its own footer. -->
    <div v-if="!footerless" class="jv-pool-savebar" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;justify-content:flex-end;">
      <span v-if="saveBlocked && missingVendors.length" style="font-size:13px;color:var(--amber);">
        Provide keys for: {{ missingVendors.map(providerLabel).join(', ') }}
      </span>
      <span v-else-if="dirty" style="font-size:13px;color:var(--amber);font-weight:600;">● Unsaved changes - Save configuration to apply</span>
      <span v-else-if="applyStatus.kind !== 'idle'" class="jv-pool-syncpill" :class="'jv-pool-syncpill--' + applyStatus.kind">
        <span class="jv-pool-syncpill-ic" aria-hidden="true"></span>{{ applyStatus.text }}
      </span>
      <button v-if="editable" @click="save" :disabled="saving || saveBlocked" class="jv-btn jv-btn--primary">
        {{ saving ? 'Saving…' : 'Save configuration' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from "vue"
import * as api from "@/api"
import {
  deriveMode, reorder, presetToModels, missingVendorKeys, validatePool,
  PROVIDER_LABELS, providerLabel, providerId, seedRowsFromConfig, defaultSubscriptionModel,
} from "@/llm/pool"
import { errMessage as _err } from "@/lib/errors"
import JvCombo from "@/components/JvCombo.vue"
import DirectSubscriptionCard from "@/components/DirectSubscriptionCard.vue"

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
  // getDirectSubscriptionStatus() payload from the host (AiModelsPane), for a
  // tenant on the legacy flat-field DIRECT path (empty models[], creds live
  // outside this editor's config). null/absent = no direct subscription -
  // never passed by onboarding, which has nothing to probe yet. Only
  // is_direct_subscription synthesizes a row here; a merely-pooled single
  // subscription (is_single_subscription_pool) already renders as a normal
  // row via rows.value and needs no special-casing.
  directStatus: { type: Object, default: null },
})
const emit = defineEmits(["saved", "ready", "direct-changed"])

// ---- state ---------------------------------------------------------------
const cfg = ref({ models: [], preset: "", routing_mode: "failover", proxy_active: false })
const catalog = ref([])
const rows = ref([])              // canonical camelCase rows (single source of truth)
const llmMode = ref("quick")      // "quick" | "preset" | "custom"
const selectedPreset = ref("")
const keysByVendor = ref({})
const err = ref("")
const saving = ref(false)
const sync = ref({ last_sync_status: "", pending: false, subscription_status: "", warnings: [] })
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
// (rotationOpts removed with the Account-rotation select. The VALUE still ships:
// newRow()/setCredType seed rotation:"sticky", matching the schema default. Restore
// this list if the control ever comes back.)
const upstreamOpts = [
  { value: "openai", label: "OpenAI" },
  { value: "google", label: "Google Gemini" },
]
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
// Not llmMode-gated: llmMode is always "custom" for the settings (!singleMode)
// editor now (Quick/Preset tabs are gone), so this only needs to ask "is a
// preset currently selected (via selectPreset, reused verbatim by the
// config-section's 'From a preset' source) with vendor keys still missing?"
const saveBlocked = computed(() => !!selectedPreset.value && missingVendors.value.length > 0)

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
// Save-bar status pill (Option A - "honest model health"). Reflects the outcome
// of the most recent apply, including any per-account subscription warnings the
// backend surfaced (e.g. a chat subscription that rejected a test request).
const applyStatus = computed(() => {
  if (sync.value.pending) return { kind: "pending", text: "Applying to your agent…" }
  const s = sync.value.last_sync_status || ""
  if (s.startsWith("failed")) return { kind: "failed", text: "Sync failed — try again" }
  if (s.startsWith("ok")) {
    let n = Array.isArray(sync.value.warnings) ? sync.value.warnings.length : 0
    if (n === 0 && sync.value.subscription_status === "unverified") n = 1
    if (n > 0) return { kind: "warn", text: `Applied · ${n} model${n > 1 ? "s" : ""} need${n > 1 ? "" : "s"} attention` }
    return { kind: "ok", text: "Applied" }
  }
  return { kind: "idle", text: "" }
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

// Compact "source" label for a list row (unified failover list, !singleMode
// only) - e.g. "Subscription · OpenAI" / "API key · Anthropic".
function sourceChip(row) {
  if (!row) return ""
  if (row.credentialType === "subscription") return "Subscription · " + (row.upstream === "google" ? "Google" : "OpenAI")
  return "API key · " + (row.provider || "—")
}

// ---- master-detail config section (!singleMode only) --------------------
// panel: which row is being added/edited, and which source tab is active.
// "preset" only applies in add-mode - picking a card replaces the whole pool
// (selectPreset, reused verbatim) rather than editing panelRow.
const panel = ref({ open: false, mode: "add", index: -1, source: "subscription", addBackups: true })
const panelRow = computed(() => rows.value[panel.value.index] || null)
function isRowEmpty(r) {
  if (!r) return true
  if (r.credentialType === "subscription") return !((r.accounts || []).length)
  return !((r.model || "").trim()) && !((r.apiKey || "").trim()) && !r.hasKey
}
// Append a blank row up-front (not on a later "commit") so finishConnect's
// !footerless auto-save - which can fire while this panel is still open -
// already includes it instead of silently dropping an in-progress connect.
function openAdd() {
  const r = { ...newRow(), order: rows.value.length }
  // Open a NEW row on Chat subscription. newRow() seeds credentialType "api_key"
  // (it is the shape the row object defaults to), which meant "+ Add a model"
  // always landed on the API-key tab regardless of what the customer already had.
  // Subscription is the path most customers take -- sign in with a plan they own,
  // no key to paste -- so it is the better first stop. (It has never followed the
  // last row's type; that would be unpredictable.)
  setCredType(r, "subscription")
  rows.value = [...rows.value, r]
  panel.value = { open: true, mode: "add", index: rows.value.length - 1, source: "subscription", addBackups: true }
}
function openEdit(i) {
  const r = rows.value[i]
  if (!r) return
  panel.value = { open: true, mode: "edit", index: i, source: r.credentialType === "subscription" ? "subscription" : "api_key", addBackups: true }
}
// Resilient-by-default (API KEYS ONLY - no subscription presets exist and
// multi-model-per-account is unconfirmed for cliproxy, so subscriptions never
// auto-add backups). Finds the catalog's single-vendor preset for this
// provider, if any.
function vendorSinglePreset(provider) {
  const pid = providerId(provider)
  return catalog.value.find((c) => c.kind === "single_vendor" && (c.models || []).length > 0 && (c.models || []).every((m) => m.provider === pid))
}
// Expand a freshly-added api_key row into its provider's full single-vendor
// failover chain, sharing the same key - additive only (never touches other
// rows), and only for models not already present for this provider.
function expandApiKeyBackups(r) {
  const preset = vendorSinglePreset(r.provider)
  if (!preset) return
  const models = presetToModels(preset, {})
  const existing = new Set(rows.value.filter((x) => x.credentialType === "api_key" && x.provider === r.provider).map((x) => x.model))
  const toAdd = models.filter((m) => m.model !== r.model && !existing.has(m.model))
  if (!toAdd.length) return
  const base = rows.value.length
  const extra = toAdd.map((m, i) => ({
    provider: r.provider, model: m.model, apiKey: r.apiKey, baseUrl: r.baseUrl, hasKey: false,
    credentialType: "api_key", rotation: "sticky", upstream: "openai",
    accounts: [], _connect: blankConnect(), order: base + i,
  }))
  rows.value = [...rows.value, ...extra]
}
// List row's "Reconnect" shortcut: open the panel AND jump straight into the
// sign-in flow (re-using the first account's slot if one exists) instead of
// making the user find "+ Add account" inside the panel themselves.
function quickReconnect(i) {
  const r = rows.value[i]
  if (!r) return
  openEdit(i)
  startConnect(r, (r.accounts && r.accounts.length) ? 0 : null)
}
function setPanelSource(src) {
  panel.value.source = src
  if (src === "preset") return
  const r = panelRow.value
  if (r) setCredType(r, src)
}
// Closing the panel (Cancel/Done/Close) - an add-row that was opened but
// never filled in (no preset picked) is dropped so an abandoned "+ Add
// model" doesn't leave a dead row in the pool.
function closePanel() {
  const idx = panel.value.index
  const r = rows.value[idx]
  // Add-mode api_key row, checkbox on, filled in: expand into the vendor's
  // resilience chain before the empty-row cleanup below (a freshly-expanded
  // row is never "empty").
  if (panel.value.mode === "add" && panel.value.source === "api_key" && panel.value.addBackups &&
      r && (r.provider || "").trim() && ((r.apiKey || "").trim() || r.hasKey)) {
    expandApiKeyBackups(r)
  }
  if (panel.value.mode === "add" && panel.value.source !== "preset" && idx >= 0 && idx < rows.value.length && isRowEmpty(rows.value[idx])) {
    rows.value = rows.value.filter((_, j) => j !== idx)
  }
  panel.value = { open: false, mode: "add", index: -1, source: "subscription", addBackups: true }
}

// ---- direct subscription (legacy flat-field path) as a list row ---------
// !singleMode only - onboarding never passes directStatus. Rendered OUTSIDE
// rows.value/save() entirely (verdict §3: never round-trip a direct row
// through save_llm_pool, which would migrate direct -> proxy); DirectSubscriptionCard
// keeps owning the actual reauthorize/disconnect flow, unchanged.
const showDirectRow = computed(() => !singleMode.value && !!(props.directStatus && props.directStatus.is_direct_subscription))
const directPanelOpen = ref(false)
watch(() => props.directStatus, (v) => { if (!v || !v.is_direct_subscription) directPanelOpen.value = false })
function onDirectCardChanged() {
  directPanelOpen.value = false
  emit("direct-changed")
}
async function removeDirect() {
  if (!window.confirm("Disconnect the chat subscription? Jarvis chat will stop working until you reconnect.")) return
  try {
    const res = await api.disconnectSubscription()
    if (!res || res.ok === false) { err.value = (res && res.error && res.error.message) || "Disconnect failed."; return }
    directPanelOpen.value = false
    emit("direct-changed")
  } catch (e) { err.value = _err(e) }
}

// What the list row shows in the model cell.
// This used to be `row.model || row.provider || '—'`, which was wrong for a
// SUBSCRIPTION row: newRow() seeds `provider` with providerOptions[0] ("Anthropic")
// because that field belongs to the api-key shape, and it is never cleared when the
// row is switched to a subscription. So a row whose chip correctly read
// "Subscription · OpenAI" displayed the model "Anthropic" -- a provider name, in the
// model column, for the wrong provider. Never fall back to `provider` here.
function rowModelLabel(row) {
  if (row.model) return row.model
  if (row.credentialType === "subscription") return "Model not set"
  return row.provider || "—"
}

function newRow() {
  return {
    provider: providerOptions[0] || "Anthropic", model: "", apiKey: "", baseUrl: "", hasKey: false,
    credentialType: "api_key", rotation: "sticky", upstream: "openai",
    accounts: [], _connect: blankConnect(), order: 0,
  }
}

function setCredType(m, type) {
  m.credentialType = type
  if (type === "subscription") {
    if (!m.rotation) m.rotation = "sticky"
    if (!m.upstream) m.upstream = "openai"
    if (!Array.isArray(m.accounts)) m.accounts = []
    if (!m._connect) m._connect = blankConnect()
    // The model field is hidden for chat subscriptions in BOTH editors now (a plan
    // grants its model; typing a model id was busywork and an easy way to enter an
    // invalid one). validatePool + save still REQUIRE a model id, so derive it from
    // the chosen provider. Dropping this would make every subscription save fail
    // validation with "model is required".
    m.model = defaultSubscriptionModel(m.upstream)
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
  if (m.credentialType !== "subscription") return
  // Was gated on singleMode; the settings editor now hides the model field too, so
  // it needs the same derivation. Changing provider must also clear the accounts:
  // an OAuth account is authorized against ONE provider, so keeping OpenAI accounts
  // on a row switched to Anthropic would ship a pool whose credentials can't serve it.
  m.model = defaultSubscriptionModel(m.upstream)
  m.accounts = []
  m._connect = blankConnect()
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
function firstWarningMessage() {
  return (sync.value.warnings && sync.value.warnings[0] && sync.value.warnings[0].message) || ""
}
// Option A "honest model health": the connected-account dot + label for a model
// row. Subscriptions reflect the fleet's last subscription-probe result;
// api-key rows stay a quiet green (a saved key is validated at save time, not
// probed live). Onboarding (singleMode) never shows this - always neutral.
function accountHealth(m) {
  if (singleMode.value) return { level: "neutral" }
  if (!m || m.credentialType !== "subscription") return { level: "ok" }
  // Config changed but not yet (re)applied - the last probe result no longer
  // describes what's about to be saved, so don't assert a stale health.
  if (dirty.value || sync.value.pending) return { level: "neutral" }
  const status = sync.value.subscription_status
  if (status === "unverified") {
    return {
      level: "warn",
      label: "Not accepting requests",
      title: firstWarningMessage() || "This subscription rejected a test request — reconnect to restore chat.",
    }
  }
  if (status === "unchecked") {
    return {
      level: "unchecked",
      label: "Not verified yet",
      title: "We couldn't confirm this subscription is active — it will be re-checked on the next apply.",
    }
  }
  // "verified", "not_applicable", "", or undefined (backend without the field) -
  // all degrade to today's quiet green.
  return { level: "ok" }
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
  // Carry any already-typed callback URL across the reset: re-opening sign-in
  // (e.g. Reconnect, or retrying after an error) must not wipe pasted text.
  m._connect = { ...blankConnect(), open: true, loading: true, reconnectIdx, pastedUrl: (m._connect.pastedUrl || "") }
  // Open the sign-in tab SYNCHRONOUSLY, inside this click, so the browser treats
  // it as user-initiated. A window.open() after the await below loses the user
  // gesture and gets popup-blocked, which is why "Open sign-in" used to need a
  // second click (the first only fetched the URL). We navigate this blank tab
  // once the authorize URL resolves; if it was blocked (win === null) the visible
  // "Open sign-in ↗" link is still there for the user to click manually.
  let win = null
  try { win = window.open("about:blank", "_blank"); if (win) win.opener = null } catch (e) { win = null }
  try {
    const provider = m.upstream === "google" ? "Google Gemini" : "OpenAI"
    const res = await api.beginPoolAccountSignin(provider, m.model.trim())
    // Backend returns an envelope: {ok:true, data:{nonce, authorize_url, …}} or
    // {ok:false, error:{code, message}}. Unwrap data; surface errors instead of
    // hanging on "Starting sign-in…".
    if (!res || res.ok === false) {
      m._connect.loading = false
      m._connect.error = (res && res.error && res.error.message) || "Couldn't start sign-in. Try again."
      if (win) win.close()
      return
    }
    const d = res.data || {}
    m._connect.nonce = d.nonce
    m._connect.authorizeUrl = d.authorize_url
    m._connect.loading = false
    if (win && d.authorize_url) win.location.href = d.authorize_url
  } catch (e) { m._connect.loading = false; m._connect.error = _err(e); if (win) win.close() }
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
    } else {
      // Settings (!singleMode) editor: always the unified failover-list view -
      // Quick/Preset tabs are gone, "From a preset" now lives inside the
      // config-section add flow (seedFromPreset/selectPreset), so llmMode never
      // needs to be "preset" or "quick" here.
      llmMode.value = "custom"
      selectedPreset.value = ""
      if (!rows.value.length) rows.value = [newRow()]
    }
    // Baseline for the unsaved-changes notice - the pool as just loaded is clean.
    savedSnapshot.value = poolSnapshot()
  } catch (e) { err.value = _err(e) }
  // A sync may already be in flight when the editor mounts (page reload
  // mid-provisioning, wizard resume via reason llm_pool_provisioning): start
  // the poller for a pending one - polling only from save() left a resumed
  // session staring at a permanent "Syncing…" banner that never picked up
  // the background job's ok/failed flip.
  try {
    sync.value = (await api.getLlmSyncStatus()) || sync.value
    if (sync.value && sync.value.pending) startPolling()
  } catch (e) { /* non-fatal */ }
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
/* ===== Account editor (!singleMode) row redesign - "Option A: refine in
   place". Onboarding's singleMode cards below are untouched; these jv-pool-*
   classes are new and only ever rendered from the !singleMode branches. ===== */
.jv-pool-rowhead { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
/* 1-based failover-order badge. */
.jv-pool-badge {
  flex: none; width: 22px; height: 22px; border-radius: 6px;
  background: var(--blue-bg); color: var(--blue); font-size: 11.5px; font-weight: 700;
  display: grid; place-items: center;
}
/* Credential-type segmented control (replaces the old pale text-pair toggle). */
.jv-pool-segct { display: inline-flex; border: 1px solid var(--border-2); border-radius: 8px; overflow: hidden; }
.jv-pool-segbtn {
  display: inline-flex; align-items: center; gap: 5px; height: 31px; padding: 0 11px;
  border: none; border-right: 1px solid var(--border-2); background: var(--surface); color: var(--text-2);
  font-family: inherit; font-size: 12.5px; font-weight: 500; cursor: pointer;
  transition: background .15s, color .15s;
}
.jv-pool-segbtn:last-child { border-right: none; }
.jv-pool-segbtn svg { flex: none; }
.jv-pool-segbtn.on { background: var(--text); color: var(--surface); font-weight: 600; }
.jv-pool-segbtn:disabled { cursor: default; opacity: .6; }
/* Reorder / remove icon buttons (replace the ▲/▼/✕ glyph squares). */
.jv-pool-iconbtn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border-radius: 6px; padding: 0;
  border: 1px solid var(--border); background: var(--surface); color: var(--text-2);
  cursor: pointer; transition: background .15s, color .15s;
}
.jv-pool-iconbtn:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
.jv-pool-iconbtn:disabled { cursor: default; opacity: .4; }
.jv-pool-iconbtn--danger { border-color: var(--red-bd); background: var(--red-bg); color: var(--red); }
.jv-pool-iconbtn--danger:hover:not(:disabled) { background: var(--red-bg); color: var(--red); }
/* Labeled field columns (Provider / Model / API key / Base URL, Model /
   Provider / Account rotation). Flex proportions stay on this wrapper - the
   input/select inside just fills width:100%. */
.jv-pool-field { display: flex; flex-direction: column; min-width: 0; }
.jv-pool-lab { font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .03em; color: var(--text-3); margin-bottom: 3px; }
/* Connected-accounts chip list. */
.jv-pool-accts { margin-top: 16px; margin-bottom: 8px; }
.jv-pool-accts > .jv-pool-lab { margin-bottom: 6px; }
.jv-pool-acctlist { display: flex; flex-direction: column; gap: 6px; }
.jv-pool-acctchip {
  display: flex; align-items: center; gap: 8px;
  border: 1px solid var(--border); background: var(--surface);
  border-radius: 8px; padding: 7px 10px;
}
.jv-pool-avatar {
  flex: none; width: 22px; height: 22px; border-radius: 50%;
  background: var(--blue-bg); color: var(--blue); font-size: 10.5px; font-weight: 700;
  display: grid; place-items: center;
}
.jv-pool-accttx { font-size: 12.5px; color: var(--text); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jv-pool-dot { flex: none; width: 7px; height: 7px; border-radius: 50%; background: var(--green); }
/* Option A "honest model health" - dot color reflects the fleet's last
   subscription probe. --ok/--neutral both render the pre-existing green so a
   backend without the field (or a config mid-edit) looks exactly as before. */
.jv-pool-dot--ok, .jv-pool-dot--neutral { background: var(--green); }
.jv-pool-dot--warn { background: var(--amber); }
.jv-pool-dot--unchecked { background: var(--text-3); }
.jv-pool-acct-health { flex: none; font-size: 12px; font-weight: 600; white-space: nowrap; }
.jv-pool-acct-health--warn { color: var(--amber); }
.jv-pool-acct-health--unchecked { color: var(--text-3); }
.jv-pool-acctacts { margin-left: auto; display: flex; gap: 6px; flex: none; }
.jv-pool-disc { color: var(--red); }
.jv-pool-disc:hover:not(:disabled) { color: var(--red); border-color: var(--red-bd); background: var(--red-bg); }
/* Full-width dashed "+ Add account" row appended to a non-empty chip list. */
.jv-pool-addrow {
  display: flex; align-items: center; justify-content: center;
  width: 100%; height: 32px; border-radius: 8px;
  border: 1px dashed var(--border-2); background: transparent; color: var(--text-2);
  font-family: inherit; font-size: 12px; font-weight: 600; cursor: pointer;
  transition: background .15s, color .15s;
}
.jv-pool-addrow:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
.jv-pool-addrow:disabled { opacity: .5; cursor: default; }
/* Save-bar apply-status pill (Option A "honest model health") - reflects the
   outcome of the last apply once there are no unsaved edits sitting on top
   of it. Same quiet weight as the rest of this settings UI. */
.jv-pool-syncpill {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12.5px; font-weight: 600; padding: 3px 10px;
  border-radius: 999px; border: 1px solid transparent;
}
.jv-pool-syncpill-ic { flex: none; display: inline-flex; align-items: center; justify-content: center; width: 10px; }
.jv-pool-syncpill--ok { color: var(--green); background: var(--green-bg); border-color: var(--green-bd); }
.jv-pool-syncpill--ok .jv-pool-syncpill-ic::before { content: "✓"; }
.jv-pool-syncpill--warn { color: var(--amber); background: var(--amber-bg); border-color: var(--amber-bd); }
.jv-pool-syncpill--warn .jv-pool-syncpill-ic::before { content: "⚠"; }
.jv-pool-syncpill--failed { color: var(--red); background: var(--red-bg); border-color: var(--red-bd); }
.jv-pool-syncpill--failed .jv-pool-syncpill-ic::before { content: "⚠"; }
.jv-pool-syncpill--pending { color: var(--text-3); background: transparent; }
.jv-pool-syncpill--pending .jv-pool-syncpill-ic {
  width: 6px; height: 6px; border-radius: 50%; background: var(--text-3);
  animation: jv-pool-pulse 1.1s ease-in-out infinite;
}
@keyframes jv-pool-pulse {
  0%, 100% { opacity: .35; }
  50% { opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
  .jv-pool-segbtn, .jv-pool-iconbtn, .jv-pool-addrow { transition: none; }
  .jv-pool-syncpill--pending .jv-pool-syncpill-ic { animation: none; opacity: .7; }
}

/* Unified failover list row (!singleMode only) - order badge, source chip,
   model id, health dot, RIGHT-ALIGNED actions cluster. */
.jv-flist-row {
  display: flex; align-items: center; gap: 9px; flex-wrap: wrap;
  border: 1px solid var(--border); border-radius: 9px; padding: 9px 11px; margin-bottom: 8px;
  background: var(--surface-1); transition: border-color .15s;
}
.jv-flist-row:hover { border-color: var(--border-2); }
@media (prefers-reduced-motion: reduce) { .jv-flist-row { transition: none; } }
.jv-flist-chip {
  flex: none; font-size: 11.5px; font-weight: 600; color: var(--text-2);
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 999px;
  padding: 3px 9px; white-space: nowrap;
}
.jv-flist-model { font-size: 13.5px; color: var(--text); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jv-flist-acts { margin-left: auto; display: flex; gap: 6px; align-items: center; flex: none; }
/* An unset model reads as a placeholder, not as a real model id. */
.jv-flist-model--unset { color: var(--text-3); font-style: italic; }

/* ---- explainer + add affordance + failover nudge (settings editor only) ----
   Flat neutral surfaces, monochrome accent, no decorative colour: the only hue in
   this pane stays semantic (the green Applied pill, the red Remove). */
/* ---- config panel fields -----------------------------------------------
   One grid + one input class, replacing per-field inline styles and flex ratios
   (1 / 1.5 / 1.5 / 1.5) that gave every field a different width. Two even columns
   read as a form; four uneven ones read as clutter. */
.jv-cfg-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 14px; align-items: end; }
.jv-cfg-inp {
  width: 100%; padding: 9px 12px; font-size: 14px; font-family: inherit;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface); color: var(--text); box-sizing: border-box;
  transition: border-color .15s ease;
}
.jv-cfg-inp:hover:not(:disabled) { border-color: var(--border-2); }
.jv-cfg-inp:focus { outline: none; border-color: var(--text-3); box-shadow: none; }
.jv-cfg-inp:disabled { opacity: .6; cursor: default; }
.jv-pool-opt { font-weight: 400; color: var(--text-3); }
@media (max-width: 720px) { .jv-cfg-grid { grid-template-columns: 1fr; } }

/* "Soon" tag on the not-yet-shipped preset tab. */
.jv-pool-segbtn--soon { cursor: default; opacity: .55; }
.jv-soon {
  margin-left: 6px; padding: 1px 6px; border-radius: 20px;
  background: var(--surface-3); color: var(--text-3);
  font-size: 10px; font-weight: 600; letter-spacing: .02em; text-transform: uppercase;
}

/* Dashed "the next row goes here" affordance — same language as the New skill /
   Drop a file rows. Full width so it anchors the list instead of floating. */
.jv-flist-add {
  display: flex; align-items: center; justify-content: center; gap: 7px;
  width: 100%; margin-top: 10px; padding: 11px 12px;
  border: 1px dashed var(--border-2); border-radius: 10px;
  background: transparent; color: var(--text-2);
  font-family: inherit; font-size: 13px; font-weight: 550; line-height: 1;
  cursor: pointer;
  transition: border-color .15s ease, background-color .15s ease, color .15s ease;
}
.jv-flist-add:hover:not(:disabled) { border-color: var(--text-3); background: var(--surface-1); color: var(--text); }
.jv-flist-add:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.jv-flist-add svg { color: var(--text-3); flex: none; }
.jv-flist-add:hover svg { color: var(--text); }
/* Consequence-first nudge shown while the pool has no fallback. */
.jv-flist-hint {
  display: flex; align-items: flex-start; gap: 9px;
  margin-top: 14px; padding: 11px 13px;
  border: 1px solid var(--border); border-radius: 10px; background: var(--surface-1);
  font-size: 12.5px; line-height: 1.55; color: var(--text-2);
}
.jv-flist-hint svg { flex: none; margin-top: 1px; color: var(--text-3); }
.jv-flist-hint b { color: var(--text); font-weight: 600; }
/* Master-detail config section (add/edit a row, or apply a preset). */
.jv-cfgpanel { border: 1px solid var(--border-2); border-radius: 11px; padding: 14px; margin: 4px 0 14px; background: var(--surface); }
.jv-cfgpanel-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.jv-cfgpanel-title { font-size: 13.5px; font-weight: 700; color: var(--text); }
.jv-cfgpanel-acts { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }

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
.jv-pick :deep(.jvc-field.jvc-open) { border-color: var(--border-2); }
/* The two connect steps on a connected vertical spine (preview .csteps): no
   shade boxes, a 1.5px line joins the numbered dots; step 2 reads pending
   (neutral dot) until the sign-in URL exists. */
.jv-cdivider { height: 1px; background: var(--border); margin: 20px 0 18px; }
.jv-cstep { position: relative; display: flex; gap: 14px; padding: 2px 0 22px; }
.jv-cstep:last-child { padding-bottom: 4px; }
.jv-cstep:not(:last-child)::before { content: ""; position: absolute; left: 12.5px; top: 32px; bottom: 4px; width: 1.5px; background: var(--border); }
.jv-cnum {
  width: 26px; height: 26px; border-radius: 50%; box-sizing: border-box;
  background: var(--text); color: var(--surface);
  display: grid; place-items: center; font-size: 12.5px; font-weight: 600;
  flex: none; position: relative; z-index: 1;
}
.jv-cstep.jv-pending .jv-cnum { background: var(--surface-2); color: var(--text-3); border: 1.5px solid var(--border-2); }
.jv-cbody { flex: 1; min-width: 0; }
.jv-ctit { font-size: 13.5px; font-weight: 600; margin-bottom: 3px; }
/* Step-1 header row: title left, sign-in action(s) right on the same line. */
.jv-chead { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 6px; }
.jv-chead .jv-ctit { margin-bottom: 0; }
.jv-cdesc { font-size: 12.5px; color: var(--text-3); line-height: 1.45; margin-bottom: 0; }
.jv-crow { display: flex; justify-content: flex-end; gap: 9px; flex-wrap: wrap; }
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
.jv-cbtn-primary { background: var(--text); color: var(--surface); box-shadow: 0 2px 10px rgba(20, 20, 30, .16); }
.jv-cbtn-primary:hover:not(:disabled) { color: var(--surface); transform: translateY(-1px); box-shadow: 0 8px 22px rgba(20, 20, 30, .22); }
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
.jv-ak-grid :deep(.jvc-field.jvc-open) { border-color: var(--border-2); }
.jv-ak-grid :deep(.jvc-input::placeholder) { color: var(--text-3); }
/* Preview stacks .method at 820px - the same breakpoint as the wizard's other grids. */
@media (max-width: 820px) { .jv-ct-cards, .jv-ak-grid { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) {
  .jv-ct-card, .jv-cbtn, .jv-paste,
  .jv-pick :deep(.jvc-field), .jv-ak-grid :deep(.jvc-field) { transition: none; }
}
</style>
