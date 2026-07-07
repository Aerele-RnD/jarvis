<template>
  <!-- DIRECT single chat-subscription re-authorize / disconnect card.
       Shown by AccountView when get_direct_subscription_status reports a tenant
       on the legacy flat-field OAuth path (empty models[], auth_mode oauth/
       subscription). These tenants are served by the container's
       auth-profiles.json, NOT the pooled cliproxy sidecar, so we re-authorize
       via the DIRECT begin/complete_paste_signin flow (which pushes a fresh
       blob + rewrites the flat fields) rather than routing them through the
       pool editor. Ports the desk account page's Screen 2/3 paste-back UI. -->
  <div class="jv-dsub" style="font-family:inherit;color:var(--text);">
    <!-- ===== Paste-back flow (Screen 2) ===== -->
    <div v-if="flowOpen">
      <p class="jv-dsub-step"><b>Step 1</b> — Sign in with your {{ status.provider || 'provider' }} account in a new tab.</p>
      <div class="jv-dsub-actions" style="margin-bottom:10px;">
        <a v-if="authorizeUrl" :href="authorizeUrl" target="_blank" rel="noopener noreferrer" class="jv-dsub-btn jv-dsub-btn-primary">Open sign-in URL ↗</a>
        <span v-else class="jv-dsub-muted">Starting sign-in…</span>
      </div>
      <div v-if="authorizeUrl" class="jv-dsub-urlrow">
        <code class="jv-dsub-url" :title="authorizeUrl">{{ authorizeUrl }}</code>
        <button type="button" class="jv-dsub-btn jv-dsub-btn-ghost" @click="copyUrl">{{ copied ? 'Copied ✓' : 'Copy' }}</button>
      </div>
      <p class="jv-dsub-step" style="margin-top:14px;"><b>Step 2</b> — After you click Authorize, your browser shows a “This site can’t be reached” page. <b>That’s expected.</b> Copy the URL from the address bar (starts with <code>http://localhost:1455/auth/callback?code=…</code>) and paste it here:</p>
      <textarea v-model="pastedUrl" rows="3" class="jv-dsub-input" placeholder="Paste the URL from the error page here"></textarea>
      <div class="jv-dsub-actions" style="margin-top:10px;">
        <button class="jv-dsub-btn jv-dsub-btn-ghost" @click="cancelFlow">Cancel</button>
        <button class="jv-dsub-btn jv-dsub-btn-primary" :disabled="busy" @click="submitPasted">{{ busy ? 'Connecting…' : 'Submit →' }}</button>
      </div>
      <div v-if="minsLeft !== null" class="jv-dsub-hint">Link valid for ~{{ minsLeft }} minute{{ minsLeft === 1 ? '' : 's' }}.</div>
      <div v-if="err" class="jv-dsub-err">{{ err }}</div>
    </div>

    <!-- ===== Connected (Screen 3) ===== -->
    <div v-else-if="status.connected">
      <p class="jv-dsub-muted" style="margin:0 0 12px;">
        Your chat subscription is served directly to the provider. Refresh state lives inside your Jarvis container — if chat starts failing, re-authorize to mint fresh tokens.
      </p>
      <div class="jv-dsub-kv"><span>Account</span><b>{{ status.account_email || '—' }}</b></div>
      <div class="jv-dsub-kv"><span>Provider</span><b>{{ status.provider || '—' }}</b></div>
      <div class="jv-dsub-kv"><span>Model</span><b>{{ status.model || '—' }}</b></div>
      <div v-if="status.connected_at" class="jv-dsub-kv"><span>Connected</span><b>{{ connectedAtLabel }}</b></div>
      <div class="jv-dsub-actions" style="margin-top:14px;">
        <button v-if="editable" class="jv-dsub-btn jv-dsub-btn-ghost" :disabled="busy" @click="doDisconnect">Disconnect</button>
        <button v-if="editable" class="jv-dsub-btn jv-dsub-btn-primary" @click="startSignin">Re-authorize</button>
      </div>
      <div v-if="err" class="jv-dsub-err">{{ err }}</div>
    </div>

    <!-- ===== Not connected (defensive) ===== -->
    <div v-else>
      <p class="jv-dsub-muted" style="margin:0 0 12px;">
        A chat subscription is selected ({{ status.provider || 'provider' }}) but no account is connected yet.
      </p>
      <div class="jv-dsub-actions">
        <button v-if="editable" class="jv-dsub-btn jv-dsub-btn-primary" @click="startSignin">Sign in with {{ status.provider || 'provider' }} →</button>
      </div>
      <div v-if="err" class="jv-dsub-err">{{ err }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onBeforeUnmount } from "vue"
import * as api from "@/api"
import { errMessage as _err } from "@/lib/errors"
import { exactDate } from "@/utils/datetime"

const props = defineProps({
  // Shape from getDirectSubscriptionStatus(): { connected, provider, model,
  // account_email, connected_at, auth_mode, is_direct_subscription }.
  status: { type: Object, required: true },
  editable: { type: Boolean, default: true },
})
// reauthorized: a complete_paste_signin succeeded (parent reloads status +
// sync). disconnected: the subscription was torn down.
const emit = defineEmits(["reauthorized", "disconnected"])

const flowOpen = ref(false)
const nonce = ref("")
const authorizeUrl = ref("")
const expiresAt = ref(0)
const pastedUrl = ref("")
const busy = ref(false)
const err = ref("")
const copied = ref(false)

// Reactive clock so the "Link valid for ~N minutes" hint actually counts down.
// Date.now() alone is non-reactive, so a computed over it would freeze at first
// paint; nowTick is bumped by an interval that only runs while a link is live.
const nowTick = ref(Date.now())
let ticker = null
function startTicker() {
  stopTicker()
  ticker = setInterval(() => { nowTick.value = Date.now() }, 30000)
}
function stopTicker() { if (ticker) { clearInterval(ticker); ticker = null } }
onBeforeUnmount(stopTicker)

const minsLeft = computed(() =>
  expiresAt.value ? Math.max(0, Math.floor((expiresAt.value - nowTick.value) / 60000)) : null,
)
// exactDate parses the server's naive datetime in the SITE timezone (via
// frappe-ui dayjsLocal) and renders it in the viewer's zone — do NOT hand the
// raw string to new Date(), which reads it as browser-local (wrong offset) and
// can yield Invalid Date on strict engines for the 6-digit microsecond suffix.
const connectedAtLabel = computed(() => exactDate(props.status.connected_at) || "—")

function resetFlow() {
  flowOpen.value = false
  nonce.value = ""
  authorizeUrl.value = ""
  expiresAt.value = 0
  pastedUrl.value = ""
  copied.value = false
  stopTicker()
}
function cancelFlow() { resetFlow(); err.value = "" }

// Re-authorize reuses the customer's already-chosen provider + model — the
// backend coerces the model to a valid subscription model for that provider.
async function startSignin() {
  err.value = ""
  busy.value = true
  flowOpen.value = true
  authorizeUrl.value = ""
  try {
    const res = await api.beginPasteSignin(props.status.provider || "", props.status.model || "")
    if (!res || res.ok === false) {
      err.value = (res && res.error && res.error.message) || "Couldn't start sign-in — try again."
      flowOpen.value = false
      return
    }
    const d = res.data || {}
    nonce.value = d.nonce
    authorizeUrl.value = d.authorize_url
    expiresAt.value = Date.now() + (Number(d.expires_in) || 0) * 1000
    startTicker()
  } catch (e) {
    err.value = _err(e)
    flowOpen.value = false
  } finally { busy.value = false }
}

async function submitPasted() {
  err.value = ""
  const pasted = (pastedUrl.value || "").trim()
  if (!pasted) { err.value = "Paste the URL from your browser's address bar first."; return }
  busy.value = true
  try {
    const res = await api.completePasteSignin(nonce.value, pasted)
    if (!res || res.ok === false) {
      const code = (res && res.error && res.error.code) || ""
      err.value = `${code ? code + ": " : ""}${(res && res.error && res.error.message) || "Sign-in failed."}`
      // A dead nonce can't be retried — drop back to the connected screen.
      if (code === "expired" || code === "unknown_nonce") resetFlow()
      return
    }
    resetFlow()
    emit("reauthorized", res.data || {})
  } catch (e) { err.value = _err(e) } finally { busy.value = false }
}

async function doDisconnect() {
  if (!window.confirm("Disconnect the chat subscription? Jarvis chat will stop working until you reconnect.")) return
  err.value = ""
  busy.value = true
  try {
    const res = await api.disconnectSubscription()
    if (!res || res.ok === false) {
      err.value = (res && res.error && res.error.message) || "Disconnect failed."
      return
    }
    resetFlow()
    emit("disconnected")
  } catch (e) { err.value = _err(e) } finally { busy.value = false }
}

function copyUrl() {
  const url = authorizeUrl.value
  if (!url) return
  const done = () => { copied.value = true; setTimeout(() => { copied.value = false }, 1400) }
  const fail = () => { err.value = "Could not copy — select the URL and copy manually." }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url).then(done).catch(fail)
    return
  }
  // LAN HTTP fallback: navigator.clipboard is undefined in insecure contexts.
  // execCommand can return false WITHOUT throwing (e.g. selection disallowed) —
  // honour the boolean so a failed copy doesn't falsely flash "Copied ✓".
  const ta = document.createElement("textarea")
  ta.value = url; ta.style.position = "fixed"; ta.style.left = "-9999px"
  document.body.appendChild(ta); ta.focus(); ta.select()
  let ok = false
  try { ok = document.execCommand("copy") } catch (e) { ok = false }
  document.body.removeChild(ta)
  ok ? done() : fail()
}
</script>

<style scoped>
.jv-dsub-step { font-size: 13px; color: var(--text-2); margin: 0 0 8px; line-height: 1.5; }
.jv-dsub-muted { font-size: 13px; color: var(--text-3); }
.jv-dsub-actions { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
.jv-dsub-btn {
  font-size: 13px; font-weight: 600; padding: 8px 16px; border-radius: 7px;
  cursor: pointer; border: 1px solid var(--border); text-decoration: none;
  display: inline-flex; align-items: center;
}
.jv-dsub-btn:disabled { opacity: .6; cursor: not-allowed; }
.jv-dsub-btn-primary { background: var(--blue); color: #fff; border-color: var(--blue); }
.jv-dsub-btn-ghost { background: var(--surface); color: var(--text-2); }
.jv-dsub-input {
  width: 100%; box-sizing: border-box; padding: 9px 12px; font-size: 14px;
  border: 1px solid var(--border); border-radius: 6px; background: var(--surface);
  color: var(--text); font-family: inherit; resize: vertical;
}
.jv-dsub-urlrow { display: flex; gap: 8px; align-items: center; }
.jv-dsub-url {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 12px; padding: 7px 10px; border: 1px solid var(--border); border-radius: 6px;
  background: var(--surface-2); color: var(--text-2);
}
/* Match AccountView's sibling .jv-acct-kv rows so the two cards read as one system. */
.jv-dsub-kv { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; padding: 5px 0; border-bottom: 1px solid var(--border); }
.jv-dsub-kv span { color: var(--text-3); }
.jv-dsub-kv b { text-align: right; word-break: break-word; }
.jv-dsub-hint { margin-top: 12px; font-size: 12px; color: var(--text-3); }
.jv-dsub-err { margin-top: 10px; font-size: 13px; color: var(--red); }
</style>
