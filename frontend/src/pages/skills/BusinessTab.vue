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
					:loading="notes.loading"
					@click="reloadAll"
				/>
			</template>
		</LayoutHeader>

		<div class="min-h-0 flex-1 overflow-y-auto">
			<div class="mx-auto flex w-full max-w-4xl flex-col gap-5 px-5 py-5">
				<!-- ══════════════ Tell Jarvis ══════════════ -->
				<section class="rounded-lg border p-4">
					<div class="text-base font-semibold text-ink-gray-9">
						Tell Jarvis about your business
					</div>
					<div class="mt-0.5 text-sm text-ink-gray-6">
						Record or type notes about how your business runs — Jarvis processes them daily
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
							Voice transcription isn't enabled on this site — type your note below.
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

				<!-- ══════════════ My notes ══════════════ -->
				<section class="rounded-lg border p-4">
					<div class="text-base font-semibold text-ink-gray-9">My notes</div>
					<div class="mt-0.5 text-sm text-ink-gray-6">
						Notes you've saved. Processed daily — proposals show up on the Learning tab.
					</div>

					<div v-if="notes.loading && !notes.rows.length" class="py-8 text-center">
						<LoadingIndicator class="size-5 text-ink-gray-5" />
					</div>
					<div
						v-else-if="!notes.rows.length"
						class="mt-3 flex flex-col items-center gap-1 rounded-lg border border-dashed py-10 text-center"
					>
						<FeatherIcon name="mic" class="size-6 text-ink-gray-5" />
						<span class="mt-1 text-base font-medium text-ink-gray-8">No notes yet</span>
						<span class="text-p-base text-ink-gray-6">
							Record or type your first note above.
						</span>
					</div>
					<div v-else class="mt-2 divide-y">
						<div
							v-for="row in notes.rows"
							:key="row.name"
							class="flex items-start justify-between gap-3 py-3"
						>
							<div class="min-w-0 flex-1">
								<p class="line-clamp-2 text-sm text-ink-gray-8">
									{{ row.excerpt || row.transcript }}
								</p>
								<div class="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink-gray-5">
									<Tooltip :text="exactDate(row.creation)">
										<span>{{ timeAgo(row.creation) }}</span>
									</Tooltip>
									<Badge
										variant="subtle"
										:theme="NOTE_THEME[row.status] || 'gray'"
										:label="row.status"
									/>
									<span v-if="row.context_type === 'Conversation'">· from chat</span>
								</div>
							</div>
							<Button
								variant="ghost"
								icon="trash-2"
								:tooltip="'Delete note'"
								:loading="deleting === row.name"
								:disabled="!!deleting"
								@click="confirmDeleteNote(row)"
							/>
						</div>
					</div>

					<div v-if="notes.hasMore" class="mt-2 flex justify-center">
						<Button
							variant="subtle"
							label="Load more"
							:loading="notes.loading"
							@click="fetchNotes('more')"
						/>
					</div>
				</section>

				<!-- ══════════════ Processing (SM only) ══════════════ -->
				<section v-if="status.can_process" class="rounded-lg border p-4">
					<div class="text-base font-semibold text-ink-gray-9">Processing</div>
					<div class="mt-0.5 text-sm text-ink-gray-6">
						Voice notes across the org are processed once a day into Learning proposals and
						wiki updates.
					</div>

					<div class="mt-3 flex flex-col gap-1.5 text-sm">
						<div class="flex flex-wrap items-center gap-x-2 gap-y-1">
							<span class="text-ink-gray-5">Last processed:</span>
							<Tooltip v-if="status.last_processed_at" :text="exactDate(status.last_processed_at)">
								<span class="text-ink-gray-8">{{ timeAgo(status.last_processed_at) }}</span>
							</Tooltip>
							<span v-else class="text-ink-gray-6">never</span>
							<template v-if="status.org_new_notes != null">
								<span class="text-ink-gray-4">·</span>
								<span class="text-ink-gray-6">
									{{ status.org_new_notes }} new note{{ status.org_new_notes === 1 ? "" : "s" }}
									org-wide
								</span>
							</template>
						</div>
						<div v-if="status.last_process_status" class="text-ink-gray-6">
							{{ status.last_process_status }}
						</div>
					</div>

					<div class="mt-4">
						<Button
							variant="subtle"
							label="Process notes now"
							iconLeft="play"
							:loading="processing"
							@click="processNow"
						/>
					</div>
				</section>

				<!-- ══════════════ Org wiki pointer ══════════════ -->
				<section class="rounded-lg border p-4">
					<div class="flex flex-wrap items-center justify-between gap-3">
						<div class="min-w-0">
							<div class="text-base font-semibold text-ink-gray-9">Org wiki has moved</div>
							<div class="mt-0.5 text-sm text-ink-gray-6">
								Browse and edit the pages Jarvis keeps about your business on the Wiki tab.
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
// BusinessTab — the "Business" tab inside the Skills page: record/type voice
// notes about how the business runs (processed daily by the voice-facts
// worker), review your own notes, and — for System Managers — trigger
// processing now. The org wiki moved to the Wiki tab (WikiTab.vue); a pointer
// card links there. Access is gated by the parent (SkillsPage probes
// get_business_status); can_process in the same payload gates the SM card.
import { ref, reactive, computed, onMounted } from "vue"
import { useRouter } from "vue-router"
import {
	Badge,
	Breadcrumbs,
	Button,
	FeatherIcon,
	FormControl,
	LoadingIndicator,
	Tooltip,
	toast,
	confirmDialog,
} from "frappe-ui"
import LayoutHeader from "@/components/LayoutHeader.vue"
import VoiceRecorder from "@/components/VoiceRecorder.vue"
import { timeAgo, exactDate } from "@/utils/datetime"
import {
	saveVoiceNote,
	listMyVoiceNotesPage,
	deleteVoiceNote,
	getBusinessStatus,
	processVoiceNotesNow,
} from "@/api/voice"

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
const NOTE_THEME = { New: "blue", Processed: "green", Archived: "gray" }

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
const deleting = ref("")
const processing = ref(false)

const notes = reactive({ rows: [], total: 0, hasMore: false, loading: false })

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
		// is transient — the page stays usable (textarea + notes still load)
		status.loaded = true
	}
}

async function fetchNotes(mode = "reset") {
	const append = mode === "more"
	notes.loading = true
	try {
		const res = await listMyVoiceNotesPage({
			start: append ? notes.rows.length : 0,
			page_length: 20,
		})
		const rows = res.rows || []
		notes.rows = append ? [...notes.rows, ...rows] : rows
		notes.total = res.total || 0
		notes.hasMore = !!res.has_more
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		notes.loading = false
	}
}

function reloadAll() {
	loadStatus()
	fetchNotes("reset")
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
		toast.success("Saved — processed daily")
		fetchNotes("reset")
		loadStatus()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		savingNote.value = false
	}
}

function confirmDiscardDraft() {
	// a tiny draft clears instantly; anything substantial (possibly minutes of
	// dictation) gets a confirm — Discard sits right next to Save
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

// ── my notes ─────────────────────────────────────────────────────────────────
function confirmDeleteNote(row) {
	if (row.status !== "Processed") {
		confirmDialog({
			title: "Delete this note?",
			message:
				"This note hasn't been processed yet — Jarvis won't learn from it if you delete it now.",
			onConfirm: async ({ hideDialog }) => {
				await doDeleteNote(row)
				hideDialog()
			},
		})
	} else {
		doDeleteNote(row)
	}
}

async function doDeleteNote(row) {
	deleting.value = row.name
	try {
		await deleteVoiceNote(row.name)
		toast.success("Note deleted")
		fetchNotes("reset")
		loadStatus()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		deleting.value = ""
	}
}

// ── processing (SM) ──────────────────────────────────────────────────────────
function processNow() {
	confirmDialog({
		title: "Process voice notes now?",
		message:
			"Runs LLM processing over all new voice notes immediately instead of waiting for the daily run. Extracted rules appear as proposals on the Learning tab; context goes into the org wiki.",
		onConfirm: async ({ hideDialog }) => {
			processing.value = true
			try {
				const r = await processVoiceNotesNow()
				hideDialog()
				if (r && r.ok === false) {
					toast.error(r.reason || "Could not start processing.")
				} else {
					toast.success("Processing started")
				}
				loadStatus()
			} catch (e) {
				toast.error(errMsg(e))
			} finally {
				processing.value = false
			}
		},
	})
}

// ── org wiki pointer ─────────────────────────────────────────────────────────
function goToWiki() {
	// hash swap on the same /skills route — SkillsPage's hash watcher flips the tab
	router.push({ hash: "#wiki" })
}

// ── init ─────────────────────────────────────────────────────────────────────
onMounted(() => {
	loadStatus()
	fetchNotes("reset")
})
</script>
