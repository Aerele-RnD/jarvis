<template>
	<!-- AI models pane (System Managers only — the dialog rail gates the section).
	     Ported from views/AccountView.vue's "AI models" card: a segmented
	     Chat-subscription | API-keys/failover control, a brief save note, and a
	     retryable load. The dialog root supplies paletteVars + .jv-dark, so the
	     shared jv-* classes resolve here without a local palette wrapper. -->
	<div class="jv-settings-body">
		<!-- brief save acknowledgement (the editors persist themselves) -->
		<div v-if="savedNote" style="display:flex;justify-content:flex-end;margin-bottom:8px;">
			<span class="jv-acct-savednote">{{ savedNote }}</span>
		</div>

		<div v-if="directSubLoading" class="jv-acct-muted">Loading…</div>

		<div v-else-if="directSubErr" class="jv-acct-err">
			Couldn't load your AI connection.
			<button class="jv-btn jv-btn--ghost jv-btn--sm" style="margin-left:8px;" @click="loadDirectSub">Retry</button>
		</div>

		<template v-else>
			<!-- Connection type. A single chat subscription is served DIRECT (codex,
			     no proxy); API keys and multi-model failover pools live in the unified
			     editor. Switching to "Chat subscription" and re-authorizing moves a
			     pooled single subscription back to direct. -->
			<div v-if="isSM" class="jv-acct-aitabs" role="tablist">
				<button type="button" role="tab" :aria-selected="aiTab === 'subscription'"
					:class="{ on: aiTab === 'subscription' }" @click="aiTab = 'subscription'">Chat subscription</button>
				<button type="button" role="tab" :aria-selected="aiTab === 'pool'"
					:class="{ on: aiTab === 'pool' }" @click="aiTab = 'pool'">API keys &amp; failover</button>
			</div>

			<!-- Chat subscription (DIRECT flat-field OAuth path): the interactive
			     re-authorize / disconnect / connect card. Same wiring as the old
			     Account page (PR #234), now hosted in the dialog. -->
			<DirectSubscriptionCard
				v-if="aiTab === 'subscription'"
				:status="directSub"
				:editable="isSM"
				@reauthorized="onDirectChanged"
				@disconnected="onDirectChanged" />

			<!-- API keys & multi-model failover pool -->
			<LlmPoolEditor v-else :editable="isSM" @saved="onSaved" />
		</template>
	</div>
</template>

<script setup>
import { ref, onMounted } from "vue"
import { getDirectSubscriptionStatus } from "@/api"
import LlmPoolEditor from "@/components/LlmPoolEditor.vue"
import DirectSubscriptionCard from "@/components/DirectSubscriptionCard.vue"

// The rail already gates this section to the tenant-admin tier; this flag
// additionally gates the editor's edit affordances + which probes fire. PART 4
// REVISED TASK 49(c): widened to System Manager OR Jarvis Admin (the LLM-config
// endpoints are all require_jarvis_admin now).
const isSM = !!(window.is_system_manager || window.is_jarvis_admin)

// ---- AI models: brief save acknowledgement (editor persists itself) --------
const savedNote = ref("")
let savedTimer = null

// ---- Direct chat-subscription (flat-field OAuth path) ----------------------
// LlmPoolEditor reads only models[]; a customer who onboarded a single chat
// subscription has an empty models[] with their creds in the flat llm_*/
// llm_oauth_* fields, so the pool editor can neither show nor re-authorize them.
// Probe getDirectSubscriptionStatus to decide the default tab; DirectSubscriptionCard
// (PR #234) renders the interactive re-authorize / disconnect / connect card.
const directSub = ref({ is_direct_subscription: false })
const directSubLoading = ref(true)
const directSubErr = ref("")

// "subscription" (direct codex) | "pool" (api-key / multi-model). Defaulted ONCE
// from the stored config — a direct subscription OR a single-subscription pool
// opens on the Chat-subscription tab; everything else opens on the pool editor.
// After that the user's tab choice sticks.
const aiTab = ref("pool")
let aiTabInit = false

async function loadDirectSub() {
	if (!isSM) { directSubLoading.value = false; return }
	directSubLoading.value = true
	directSubErr.value = ""
	try {
		// Race a client timeout so a hung probe can't strand the section on
		// "Loading…" forever (the pool editor renders behind it).
		const timeout = new Promise((_, rej) => setTimeout(() => rej(new Error("timed out")), 12000))
		directSub.value = (await Promise.race([
			getDirectSubscriptionStatus(),
			timeout,
		])) || { is_direct_subscription: false }
		if (!aiTabInit) {
			aiTab.value = (directSub.value.is_direct_subscription || directSub.value.is_single_subscription_pool) ? "subscription" : "pool"
			aiTabInit = true
		}
	} catch (e) {
		// Don't silently drop a real direct-subscription tenant onto the empty
		// pool editor — surface a retryable error instead of a dead end.
		directSub.value = { is_direct_subscription: false }
		directSubErr.value = (e && (e.message || e._server_messages)) || "Couldn't load your AI connection."
	} finally {
		directSubLoading.value = false
	}
}

// DirectSubscriptionCard emitted reauthorized/disconnected — re-probe status so
// the fields + tab reflect the new state.
async function onDirectChanged() {
	await loadDirectSub()
}

// After a pool save (which can migrate direct<->pool): flash the note and
// re-probe direct status. aiTab is already initialised, so the tab won't jump.
async function onSaved(sync) {
	savedNote.value = sync && sync.pending ? "Saved — syncing…" : "Saved"
	clearTimeout(savedTimer)
	savedTimer = setTimeout(() => { savedNote.value = "" }, 4000)
	await loadDirectSub()
}

onMounted(loadDirectSub)
</script>
