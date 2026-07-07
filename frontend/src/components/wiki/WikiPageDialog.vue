<template>
	<Dialog
		v-model="show"
		:options="{ title: (page && page.title) || 'Wiki page', size: 'lg' }"
	>
		<template #body-content>
			<div v-if="loading" class="py-8 text-center">
				<LoadingIndicator class="size-5 text-ink-gray-5" />
			</div>
			<template v-else-if="page">
				<!-- metadata row: type · scope (+target) · slug · updated · flags -->
				<div class="flex flex-wrap items-center gap-2 text-sm">
					<Badge variant="outline" theme="gray" :label="page.page_type" />
					<Badge
						variant="subtle"
						:theme="SCOPE_THEME[page.scope] || 'gray'"
						:label="page.scope || 'Org'"
					/>
					<span v-if="scopeTarget" class="text-ink-gray-5">for {{ scopeTarget }}</span>
					<Badge
						v-if="page.status === 'Archived'"
						variant="subtle"
						theme="gray"
						label="Archived"
					/>
					<span class="text-ink-gray-5">{{ page.slug }}</span>
					<Tooltip v-if="updatedAt" :text="exactDate(updatedAt)">
						<span class="text-ink-gray-5">· updated {{ timeAgo(updatedAt) }}</span>
					</Tooltip>
					<Badge
						v-if="page.contradiction_flag"
						variant="subtle"
						theme="red"
						label="Conflicting"
					/>
					<Badge v-if="page.stale" variant="subtle" theme="orange" label="Stale" />
				</div>

				<!-- mirrors the amber Stale badge on the list row -->
				<div
					v-if="page.stale"
					class="mt-3 rounded-lg border border-outline-amber-2 bg-surface-amber-1 px-3 py-2 text-sm text-ink-amber-3"
				>
					Not confirmed in 90+ days{{ page.can_edit ? " — saving an edit marks it reviewed." : "." }}
				</div>

				<template v-if="editing">
					<FormControl
						type="textarea"
						class="mt-3"
						label="Summary"
						:rows="2"
						:modelValue="editSummary"
						@update:modelValue="(v) => (editSummary = v)"
					/>
					<FormControl
						type="textarea"
						class="mt-3"
						label="Body (markdown)"
						:rows="14"
						:modelValue="editBody"
						@update:modelValue="(v) => (editBody = v)"
					/>
				</template>
				<template v-else>
					<p v-if="page.summary" class="mt-3 text-sm text-ink-gray-6">
						{{ page.summary }}
					</p>
					<!-- renderMarkdown from @/markdown (escapes HTML first — safe) -->
					<div
						v-if="page.body_md"
						class="prose prose-sm mt-3 max-w-none"
						v-html="bodyHtml"
					/>
					<p v-else class="mt-3 text-sm text-ink-gray-5">No content yet.</p>
				</template>
			</template>
		</template>
		<template #actions>
			<div v-if="page" class="flex flex-wrap items-center gap-2">
				<template v-if="editing">
					<Button variant="solid" label="Save" :loading="saving" @click="save" />
					<Button label="Cancel" @click="editing = false" />
				</template>
				<template v-else>
					<Button
						v-if="page.can_edit"
						variant="subtle"
						label="Edit"
						iconLeft="edit-2"
						@click="startEdit"
					/>
					<Button
						v-if="page.can_archive && page.status !== 'Archived'"
						variant="subtle"
						theme="red"
						label="Archive"
						:loading="archiving"
						@click="confirmArchive"
					/>
				</template>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
// WikiPageDialog — the wiki page viewer/editor extracted from BusinessTab's
// org-wiki dialog for the Wiki tab (design D4): rendered-markdown read view
// with scope/attention metadata, an Edit toggle (summary + body) shown only
// when the server-computed `can_edit` flag allows it, and Archive behind a
// confirmDialog when `can_archive`. Fetches the page itself whenever it opens
// (v-model true + slug); emits `refresh` after a save/archive so the owning
// list refetches.
import { ref, computed, watch } from "vue"
import {
	Badge,
	Button,
	Dialog,
	FormControl,
	LoadingIndicator,
	Tooltip,
	toast,
	confirmDialog,
} from "frappe-ui"
import { renderMarkdown } from "@/markdown"
import { timeAgo, exactDate } from "@/utils/datetime"
import { getWikiPage, saveWikiPage, archiveWikiPage } from "@/api/wiki"

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	slug: { type: String, default: "" },
})
const emit = defineEmits(["update:modelValue", "refresh"])

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

const SCOPE_THEME = { Org: "gray", Role: "blue", User: "green" }

const show = computed({
	get: () => props.modelValue,
	set: (v) => emit("update:modelValue", v),
})

const page = ref(null)
const loading = ref(false)
const editing = ref(false)
const editSummary = ref("")
const editBody = ref("")
const saving = ref(false)
const archiving = ref(false)

const bodyHtml = computed(() =>
	page.value && page.value.body_md ? renderMarkdown(page.value.body_md) : ""
)
const updatedAt = computed(
	() => (page.value && (page.value.modified || page.value.last_confirmed_at)) || ""
)
const scopeTarget = computed(() => {
	if (!page.value) return ""
	if (page.value.scope === "Role") return page.value.target_role || ""
	if (page.value.scope === "User") return page.value.target_user || ""
	return ""
})

watch(
	() => props.modelValue,
	(open) => {
		if (open) load()
	}
)

async function load() {
	page.value = null
	editing.value = false
	loading.value = true
	try {
		page.value = await getWikiPage(props.slug)
	} catch (e) {
		show.value = false
		toast.error(errMsg(e))
	} finally {
		loading.value = false
	}
}

function startEdit() {
	editSummary.value = (page.value && page.value.summary) || ""
	editBody.value = (page.value && page.value.body_md) || ""
	editing.value = true
}

async function save() {
	saving.value = true
	try {
		await saveWikiPage(props.slug, {
			summary: editSummary.value,
			body_md: editBody.value,
		})
		// a saved body counts as a review server-side — mirror that locally
		if (page.value) {
			page.value.summary = editSummary.value
			page.value.body_md = editBody.value
			page.value.contradiction_flag = 0
			page.value.stale = false
		}
		editing.value = false
		toast.success("Page saved")
		emit("refresh")
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		saving.value = false
	}
}

function confirmArchive() {
	confirmDialog({
		title: "Archive this page?",
		message:
			"Archived pages stop appearing in the list and are no longer used as chat context. The record is kept.",
		onConfirm: async ({ hideDialog }) => {
			archiving.value = true
			try {
				await archiveWikiPage(props.slug)
				hideDialog()
				show.value = false
				toast.success("Page archived")
				emit("refresh")
			} catch (e) {
				toast.error(errMsg(e))
			} finally {
				archiving.value = false
			}
		},
	})
}
</script>
