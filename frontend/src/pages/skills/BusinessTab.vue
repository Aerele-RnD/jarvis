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
					:loading="notes.loading || wiki.loading"
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

				<!-- ══════════════ Org wiki (SM only) ══════════════ -->
				<section v-if="status.can_process" class="rounded-lg border p-4">
					<div class="text-base font-semibold text-ink-gray-9">Org wiki</div>
					<div class="mt-0.5 text-sm text-ink-gray-6">
						Pages Jarvis maintains about your customers, suppliers, items and processes —
						referenced automatically in chat.
					</div>

					<div class="mt-3 flex flex-wrap items-center gap-2">
						<div class="min-w-48 flex-1">
							<FormControl
								type="text"
								placeholder="Search pages"
								:modelValue="wikiSearch"
								@update:modelValue="setWikiSearch"
							>
								<template #prefix>
									<FeatherIcon name="search" class="size-4 text-ink-gray-5" />
								</template>
							</FormControl>
						</div>
						<div class="w-44">
							<FormControl
								type="select"
								:options="TYPE_OPTIONS"
								:modelValue="wikiType"
								@update:modelValue="setWikiType"
							/>
						</div>
					</div>

					<div v-if="wiki.loading && !wiki.rows.length" class="py-8 text-center">
						<LoadingIndicator class="size-5 text-ink-gray-5" />
					</div>
					<div
						v-else-if="!wiki.rows.length"
						class="mt-3 flex flex-col items-center gap-1 rounded-lg border border-dashed py-10 text-center"
					>
						<FeatherIcon name="book-open" class="size-6 text-ink-gray-5" />
						<span class="mt-1 text-base font-medium text-ink-gray-8">
							{{ wikiSearch || wikiType ? "No pages match" : "No wiki pages yet" }}
						</span>
						<span class="text-p-base text-ink-gray-6">
							{{
								wikiSearch || wikiType
									? "Try a different search or type filter."
									: "Jarvis builds pages from voice notes and chat conversations over time."
							}}
						</span>
					</div>
					<div v-else class="mt-2 divide-y">
						<button
							v-for="row in wiki.rows"
							:key="row.slug || row.name"
							class="flex w-full items-center justify-between gap-3 py-2.5 text-left hover:bg-surface-gray-1"
							@click="openWikiPage(row)"
						>
							<div class="min-w-0 flex-1">
								<div class="flex items-center gap-1.5">
									<Tooltip v-if="row.stale" text="Not confirmed in 90+ days">
										<span
											class="size-2 shrink-0 rounded-full bg-[color:var(--ink-amber-3)]"
										/>
									</Tooltip>
									<span class="truncate text-sm font-medium text-ink-gray-8">
										{{ row.title || row.slug }}
									</span>
									<Badge variant="outline" theme="gray" :label="row.page_type" />
								</div>
								<div class="mt-0.5 flex items-center gap-2 text-sm text-ink-gray-5">
									<span class="truncate">{{ row.slug }}</span>
									<Tooltip v-if="wikiUpdated(row)" :text="exactDate(wikiUpdated(row))">
										<span class="shrink-0">· updated {{ timeAgo(wikiUpdated(row)) }}</span>
									</Tooltip>
								</div>
							</div>
							<FeatherIcon name="chevron-right" class="size-4 shrink-0 text-ink-gray-4" />
						</button>
					</div>

					<div v-if="wiki.hasMore" class="mt-2 flex justify-center">
						<Button
							variant="subtle"
							label="Load more"
							:loading="wiki.loading"
							@click="fetchWiki('more')"
						/>
					</div>
				</section>
			</div>
		</div>

		<!-- Wiki page dialog: read view (rendered markdown) with an Edit toggle -->
		<Dialog
			v-model="wikiDialog.show"
			:options="{ title: (wikiDialog.page && wikiDialog.page.title) || 'Wiki page', size: 'lg' }"
		>
			<template #body-content>
				<div v-if="wikiDialog.loading" class="py-8 text-center">
					<LoadingIndicator class="size-5 text-ink-gray-5" />
				</div>
				<template v-else-if="wikiDialog.page">
					<div class="flex flex-wrap items-center gap-2 text-sm">
						<Badge variant="outline" theme="gray" :label="wikiDialog.page.page_type" />
						<span class="text-ink-gray-5">{{ wikiDialog.page.slug }}</span>
						<Tooltip
							v-if="wikiDialog.page.last_confirmed_at"
							:text="exactDate(wikiDialog.page.last_confirmed_at)"
						>
							<span class="text-ink-gray-5">
								· confirmed {{ timeAgo(wikiDialog.page.last_confirmed_at) }}
							</span>
						</Tooltip>
						<Badge
							v-if="wikiDialog.page.contradiction_flag"
							variant="subtle"
							theme="orange"
							label="Contradiction flagged"
						/>
					</div>

					<!-- mirrors the amber stale dot on the list row -->
					<div
						v-if="wikiDialog.page.stale"
						class="mt-3 rounded-lg border border-outline-amber-2 bg-surface-amber-1 px-3 py-2 text-sm text-ink-amber-3"
					>
						Not confirmed in 90+ days
					</div>

					<p v-if="wikiDialog.page.summary" class="mt-3 text-sm text-ink-gray-6">
						{{ wikiDialog.page.summary }}
					</p>

					<FormControl
						v-if="wikiDialog.editing"
						type="textarea"
						class="mt-3"
						label="Body (markdown)"
						:rows="14"
						:modelValue="wikiDialog.editBody"
						@update:modelValue="(v) => (wikiDialog.editBody = v)"
					/>
					<template v-else>
						<!-- renderMarkdown from @/markdown (escapes HTML first — safe) -->
						<div
							v-if="wikiDialog.page.body_md"
							class="prose prose-sm mt-3 max-w-none"
							v-html="wikiBodyHtml"
						/>
						<p v-else class="mt-3 text-sm text-ink-gray-5">No content yet.</p>
					</template>
				</template>
			</template>
			<template #actions>
				<div v-if="wikiDialog.page" class="flex flex-wrap items-center gap-2">
					<template v-if="wikiDialog.editing">
						<Button
							variant="solid"
							label="Save"
							:loading="wikiDialog.saving"
							@click="saveWikiEdit"
						/>
						<Button label="Cancel" @click="wikiDialog.editing = false" />
					</template>
					<template v-else>
						<Button variant="subtle" label="Edit" iconLeft="edit-2" @click="startWikiEdit" />
						<Button
							variant="subtle"
							theme="red"
							label="Archive"
							:loading="wikiDialog.archiving"
							@click="confirmArchiveWiki"
						/>
					</template>
				</div>
			</template>
		</Dialog>
	</div>
</template>

<script setup>
// BusinessTab — the "Business" tab inside the Skills page: record/type voice
// notes about how the business runs (processed daily by the voice-facts
// worker), review your own notes, and — for System Managers — trigger
// processing now and browse/edit the org wiki Jarvis maintains. Access is
// gated by the parent (SkillsPage probes get_business_status); can_process in
// the same payload gates the two SM cards.
import { ref, reactive, computed, onMounted, onBeforeUnmount } from "vue"
import {
	Badge,
	Breadcrumbs,
	Button,
	Dialog,
	FeatherIcon,
	FormControl,
	LoadingIndicator,
	Tooltip,
	toast,
	confirmDialog,
} from "frappe-ui"
import LayoutHeader from "@/components/LayoutHeader.vue"
import VoiceRecorder from "@/components/VoiceRecorder.vue"
import { renderMarkdown } from "@/markdown"
import { timeAgo, exactDate } from "@/utils/datetime"
import {
	saveVoiceNote,
	listMyVoiceNotesPage,
	deleteVoiceNote,
	getBusinessStatus,
	processVoiceNotesNow,
	listWikiPagesPage,
	getWikiPage,
	saveWikiPage,
	archiveWikiPage,
} from "@/api/voice"

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
const WIKI_TYPES = [
	"Customer",
	"Supplier",
	"Item",
	"Process",
	"Doctype",
	"Exception",
	"Integration",
	"People",
	"Org",
]
const TYPE_OPTIONS = [
	{ label: "All types", value: "" },
	...WIKI_TYPES.map((t) => ({ label: t, value: t })),
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
const deleting = ref("")
const processing = ref(false)

const notes = reactive({ rows: [], total: 0, hasMore: false, loading: false })
const wiki = reactive({ rows: [], total: 0, hasMore: false, loading: false, loadedOnce: false })
const wikiSearch = ref("")
const wikiType = ref("")
let searchTimer = null

const wikiDialog = reactive({
	show: false,
	loading: false,
	slug: "",
	page: null,
	editing: false,
	editBody: "",
	saving: false,
	archiving: false,
})

const wordCount = computed(() => draft.value.trim().split(/\s+/).filter(Boolean).length)
const wikiBodyHtml = computed(() =>
	wikiDialog.page && wikiDialog.page.body_md ? renderMarkdown(wikiDialog.page.body_md) : ""
)

// list rows carry whichever recency field the server includes — be defensive
function wikiUpdated(row) {
	return row.modified || row.last_confirmed_at || row.creation || ""
}

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
		if (status.can_process && !wiki.loadedOnce) fetchWiki("reset")
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

async function fetchWiki(mode = "reset") {
	const append = mode === "more"
	wiki.loading = true
	wiki.loadedOnce = true
	try {
		const res = await listWikiPagesPage({
			search: wikiSearch.value,
			page_type: wikiType.value,
			start: append ? wiki.rows.length : 0,
			page_length: 20,
		})
		const rows = res.rows || []
		wiki.rows = append ? [...wiki.rows, ...rows] : rows
		wiki.total = res.total || 0
		wiki.hasMore = !!res.has_more
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		wiki.loading = false
	}
}

function reloadAll() {
	loadStatus()
	fetchNotes("reset")
	if (status.can_process) fetchWiki("reset")
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

// ── org wiki (SM) ────────────────────────────────────────────────────────────
function setWikiSearch(v) {
	wikiSearch.value = v
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => fetchWiki("reset"), 300)
}
function setWikiType(v) {
	if (wikiType.value === v) return
	wikiType.value = v
	fetchWiki("reset")
}

async function openWikiPage(row) {
	wikiDialog.slug = row.slug || row.name
	wikiDialog.page = null
	wikiDialog.editing = false
	wikiDialog.loading = true
	wikiDialog.show = true
	try {
		wikiDialog.page = await getWikiPage(wikiDialog.slug)
	} catch (e) {
		wikiDialog.show = false
		toast.error(errMsg(e))
	} finally {
		wikiDialog.loading = false
	}
}

function startWikiEdit() {
	wikiDialog.editBody = (wikiDialog.page && wikiDialog.page.body_md) || ""
	wikiDialog.editing = true
}

async function saveWikiEdit() {
	wikiDialog.saving = true
	try {
		await saveWikiPage(wikiDialog.slug, { body_md: wikiDialog.editBody })
		if (wikiDialog.page) wikiDialog.page.body_md = wikiDialog.editBody
		wikiDialog.editing = false
		toast.success("Page saved")
		fetchWiki("reset")
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		wikiDialog.saving = false
	}
}

function confirmArchiveWiki() {
	confirmDialog({
		title: "Archive this page?",
		message:
			"Archived pages stop appearing in this list and are no longer used as chat context. The record is kept.",
		onConfirm: async ({ hideDialog }) => {
			wikiDialog.archiving = true
			try {
				await archiveWikiPage(wikiDialog.slug)
				hideDialog()
				wikiDialog.show = false
				toast.success("Page archived")
				fetchWiki("reset")
			} catch (e) {
				toast.error(errMsg(e))
			} finally {
				wikiDialog.archiving = false
			}
		},
	})
}

// ── init ─────────────────────────────────────────────────────────────────────
onMounted(() => {
	loadStatus()
	fetchNotes("reset")
})
onBeforeUnmount(() => clearTimeout(searchTimer))
</script>
