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
      <table class="jv-dsub-kv">
        <tr><td>Account</td><td>{{ status.account_email || '—' }}</td></tr>
        <tr><td>Provider</td><td>{{ status.provider || '—' }}</td></tr>
        <tr><td>Model</td><td>{{ status.model || '—' }}</td></tr>
        <tr v-if="status.connected_at"><td>Connected</td><td>{{ connectedAtLabel }}</td></tr>
      </table>
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
import { ref, computed } from "vue"
import * as api from "@/api"
import { errMessage as _err } from "@/lib/errors"

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

const minsLeft = computed(() =>
  expiresAt.value ? Math.max(0, Math.floor((expiresAt.value - Date.now()) / 60000)) : null,
)
const connectedAtLabel = computed(() => {
  const raw = props.status.connected_at
  if (!raw) return "—"
  const d = new Date(raw.replace(" ", "T"))
  return isNaN(d.getTime()) ? String(raw) : d.toLocaleString()
})

function resetFlow() {
  flowOpen.value = false
  nonce.value = ""
  authorizeUrl.value = ""
  expiresAt.value = 0
  pastedUrl.value = ""
  copied.value = false
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
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(url).then(done).catch(() => { err.value = "Could not copy — select the URL and copy manually." })
    return
  }
  // LAN HTTP fallback: navigator.clipboard is undefined in insecure contexts.
  const ta = document.createElement("textarea")
  ta.value = url; ta.style.position = "fixed"; ta.style.left = "-9999px"
  document.body.appendChild(ta); ta.focus(); ta.select()
  try { document.execCommand("copy"); done() } catch (e) { err.value = "Could not copy — select the URL and copy manually." }
  document.body.removeChild(ta)
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
.jv-dsub-kv { width: 100%; border-collapse: collapse; font-size: 13px; }
.jv-dsub-kv td { padding: 5px 0; border-bottom: 1px solid var(--border); }
.jv-dsub-kv td:first-child { color: var(--text-3); width: 120px; }
.jv-dsub-hint { margin-top: 12px; font-size: 12px; color: var(--text-3); }
.jv-dsub-err { margin-top: 10px; font-size: 13px; color: var(--red); }
</style>
