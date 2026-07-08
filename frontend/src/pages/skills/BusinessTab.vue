<template>
	<div class="flex h-full flex-col overflow-hidden">
		<LayoutHeader>
			<template #left-header>
				<Breadcrumbs
					:items="[
						{ label: 'Skills', route: { name: 'SkillsList' } },
						{ label: 'Business' },
					]"
				/>
			</template>
			<template #right-header>
				<Button
					icon="refresh-cw"
					variant="ghost"
					:tooltip="'Refresh'"
					:loading="refreshing"
					@click="reloadAll"
				/>
			</template>
		</LayoutHeader>

		<div class="min-h-0 flex-1 overflow-y-auto">
			<div class="mx-auto flex w-full max-w-6xl flex-col gap-5 px-5 py-5">
				<!-- ══════════════ Capture · My notes (2-pane) ══════════════ -->
				<div class="grid grid-cols-1 gap-5 lg:grid-cols-2">
					<!-- left: capture card -->
					<section class="rounded-lg border p-4">
						<div class="text-base font-semibold text-ink-gray-9">
							Tell Jarvis about your business
						</div>
						<div class="mt-0.5 text-sm text-ink-gray-6">
							Record or type notes about how your business runs - Jarvis processes them daily
							into learned defaults and wiki knowledge it uses in chat.
						</div>

						<!-- suggestion chips: prompts to talk about, not buttons -->
						<div class="mt-3 flex flex-wrap gap-1.5">
							<span
								v-for="s in SUGGESTIONS"
								:key="s"
								class="rounded-full bg-surface-gray-2 px-2.5 py-0.5 text-sm text-ink-gray-7"
							>
								{{ s }}
							</span>
						</div>

						<div class="mt-4">
							<VoiceRecorder v-if="status.stt_enabled" @transcript="onTranscript" />
							<span v-else-if="status.loaded" class="text-sm text-ink-gray-5">
								Voice transcription isn't enabled on this site - type your note below.
							</span>
						</div>

						<FormControl
							type="textarea"
							class="mt-3"
							:rows="5"
							placeholder="e.g. We invoice all AMC customers on the 1st, except Fabrico who insist on the 15th…"
							:modelValue="draft"
							@update:modelValue="(v) => (draft = v)"
						/>
						<div class="mt-2 flex flex-wrap items-center gap-2">
							<Button
								variant="solid"
								label="Save"
								:loading="savingNote"
								:disabled="!draft.trim()"
								@click="saveNote"
							/>
							<Button
								v-if="draft.trim()"
								variant="ghost"
								label="Discard"
								@click="confirmDiscardDraft"
							/>
							<span class="ml-auto text-sm text-ink-gray-5">
								{{ wordCount }} word{{ wordCount === 1 ? "" : "s" }}
							</span>
						</div>
					</section>

					<!-- right: my notes (search / filter / edit / delete; SM
					     process-now + sweep telemetry live in its header) -->
					<NotesPane
						ref="notesPane"
						:can-process="status.can_process"
						:last-processed-at="status.last_processed_at"
						:last-process-status="status.last_process_status"
						:org-new-notes="status.org_new_notes"
						@changed="loadStatus"
					/>
				</div>

				<!-- ══════════════ Org wiki pointer ══════════════ -->
				<section class="rounded-lg border p-4">
					<div class="flex flex-wrap items-center justify-between gap-3">
						<div class="min-w-0">
							<div class="text-base font-semibold text-ink-gray-9">Browse the org wiki</div>
							<div class="mt-0.5 text-sm text-ink-gray-6">
								The pages Jarvis keeps about your business live on the Wiki tab.
							</div>
						</div>
						<Button variant="subtle" label="Go to Wiki" iconLeft="book-open" @click="goToWiki" />
					</div>
				</section>
			</div>
		</div>
	</div>
</template>

<script setup>
// BusinessTab - the "Business" tab inside the Skills page, now two panes:
// left is the capture card (record/type voice notes about how the business
// runs - processed daily by the voice-facts worker), right is NotesPane
// (search / status filter / paginate / edit-while-New / delete your own
// notes; the SM "Process notes now" control and sweep telemetry moved into
// that pane's header). The org wiki lives on the Wiki tab (WikiTab.vue); a
// pointer card links there. Access is gated by the parent (SkillsPage probes
// get_business_status); can_process in the same payload gates the SM
// controls inside NotesPane.
import { ref, reactive, computed, onMounted } from "vue"
import { useRouter } from "vue-router"
import { Breadcrumbs, Button, FormControl, toast, confirmDialog } from "frappe-ui"
import LayoutHeader from "@/components/LayoutHeader.vue"
import VoiceRecorder from "@/components/VoiceRecorder.vue"
import NotesPane from "@/components/business/NotesPane.vue"
import { saveVoiceNote, getBusinessStatus } from "@/api/voice"

const router = useRouter()

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

// ── static config ────────────────────────────────────────────────────────────
const SUGGESTIONS = [
	"What does your business do?",
	"How do you use ERPNext?",
	"Your customisations",
	"What should Jarvis handle for you?",
	"Month-end rituals",
	"Vendor & customer quirks",
]

// ── state ────────────────────────────────────────────────────────────────────
const status = reactive({
	loaded: false,
	stt_enabled: false,
	my_notes: 0,
	org_new_notes: null,
	last_processed_at: "",
	last_process_status: "",
	can_process: false,
})

const draft = ref("")
const savingNote = ref(false)
const refreshing = ref(false)
const notesPane = ref(null)

const wordCount = computed(() => draft.value.trim().split(/\s+/).filter(Boolean).length)

// ── loaders ──────────────────────────────────────────────────────────────────
async function loadStatus() {
	try {
		const st = await getBusinessStatus()
		status.stt_enabled = !!st.stt_enabled
		status.my_notes = st.my_notes || 0
		status.org_new_notes = st.org_new_notes == null ? null : st.org_new_notes
		status.last_processed_at = st.last_processed_at || ""
		status.last_process_status = st.last_process_status || ""
		status.can_process = !!st.can_process
		status.loaded = true
	} catch (e) {
		// parent mounts this only after the same probe succeeded; a failure here
		// is transient - the page stays usable (textarea + notes still load)
		status.loaded = true
	}
}

async function reloadAll() {
	refreshing.value = true
	try {
		await Promise.all([loadStatus(), notesPane.value?.reload()])
	} finally {
		refreshing.value = false
	}
}

// ── note capture ─────────────────────────────────────────────────────────────
function onTranscript(text) {
	// dictation appends to any typed draft (composer-mic precedent)
	draft.value = draft.value.trim() ? draft.value.replace(/\s+$/, "") + " " + text : text
}

async function saveNote() {
	const transcript = draft.value.trim()
	if (!transcript) return
	savingNote.value = true
	try {
		await saveVoiceNote({ transcript, context_type: "Business", source: "Business Tab" })
		draft.value = ""
		toast.success("Saved - processed daily")
		notesPane.value?.reload()
		loadStatus()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		savingNote.value = false
	}
}

function confirmDiscardDraft() {
	// a tiny draft clears instantly; anything substantial (possibly minutes of
	// dictation) gets a confirm - Discard sits right next to Save
	if (draft.value.trim().length <= 15) {
		draft.value = ""
		return
	}
	confirmDialog({
		title: "Discard this note?",
		message: "Your unsaved note will be cleared. This can't be undone.",
		onConfirm: ({ hideDialog }) => {
			draft.value = ""
			hideDialog()
		},
	})
}

// ── org wiki pointer ─────────────────────────────────────────────────────────
function goToWiki() {
	// hash swap on the same /skills route - SkillsPage's hash watcher flips the tab
	router.push({ hash: "#wiki" })
}

// ── init ─────────────────────────────────────────────────────────────────────
onMounted(() => {
	loadStatus()
})
</script>
