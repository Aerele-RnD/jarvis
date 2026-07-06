<template>
	<DocPage
		:breadcrumbs="breadcrumbs"
		:title="pageTitle"
		:status-badge="null"
		:dirty="dirty"
		:loading="loading"
		:error="loadError"
	>
		<template #actions>
			<SyncPill ref="syncPill" />
			<Badge
				v-if="skill && !canEdit"
				variant="subtle"
				theme="gray"
				size="lg"
				:label="`Shared by ${sharedBy || 'another user'} · read-only`"
			/>
			<Dropdown v-if="canEdit && !isNew" :options="overflowOptions">
				<Button icon="more-horizontal" variant="ghost" />
			</Dropdown>
			<Button
				v-if="canEdit"
				variant="solid"
				label="Save"
				:disabled="!dirty"
				:loading="saving"
				@click="save"
			/>
		</template>

		<template #main>
			<DocSection label="Details">
				<div class="space-y-4">
					<FormControl
						type="text"
						label="Name"
						placeholder="e.g. monthly-close"
						:modelValue="form.skill_name"
						:disabled="!isNew || saving"
						:description="
							isNew
								? `Lowercase letters, digits and hyphens — trigger it in chat with /${form.skill_name || 'name'}.`
								: 'Skill names can\'t be changed after creation.'
						"
						@update:modelValue="(v) => (form.skill_name = v)"
					/>
					<FormControl
						type="textarea"
						label="Description"
						:rows="2"
						placeholder="When should the assistant use this skill?"
						description="A short hint so the assistant knows when this skill applies."
						:modelValue="form.description"
						:disabled="readonly"
						@update:modelValue="(v) => (form.description = v)"
					/>
					<Switch
						v-model="form.enabled"
						label="Enabled"
						description="Off = saved as a draft, not used by the assistant."
						:disabled="readonly"
					/>
					<Switch
						v-model="form.user_invocable"
						label="User invocable"
						description="Show in the chat / menu so users can trigger it directly."
						:disabled="readonly"
					/>
				</div>
			</DocSection>

			<DocSection label="Instructions">
				<FormControl
					type="textarea"
					:rows="14"
					class="font-mono [&_textarea]:min-h-[320px]"
					placeholder="Markdown instructions the assistant follows when this skill runs…"
					description="Markdown instructions the model follows when this skill runs."
					:modelValue="form.instructions"
					:disabled="readonly"
					@update:modelValue="(v) => (form.instructions = v)"
				/>
			</DocSection>
		</template>

		<template #aside>
			<!-- new-record mode: metadata exists only after the first save -->
			<div v-if="isNew" class="m-5 rounded-md border p-4 text-sm text-ink-gray-6">
				Save to enable comments, attachments and sharing.
			</div>

			<DocMetaPanel v-else-if="canEdit && docmeta" :docmeta="docmeta" :can-write="true">
				<!-- skills keep the child-table share model (§14 F1/DA-09) -->
				<template #extra>
					<div class="px-5 py-4">
						<div class="flex items-center justify-between">
							<div class="text-sm text-ink-gray-5">Shared with</div>
							<Button label="Manage" @click="shareOpen = true" />
						</div>
						<div v-if="shares.length" class="mt-2 flex items-center">
							<Tooltip
								v-for="u in shares.slice(0, 8)"
								:key="u.name"
								:text="u.full_name || u.name"
							>
								<Avatar
									size="md"
									:label="u.full_name || u.name"
									class="-mr-1.5 ring-2 ring-outline-white hover:z-10 hover:scale-110"
								/>
							</Tooltip>
							<span v-if="shares.length > 8" class="ml-3 text-sm text-ink-gray-5">
								+{{ shares.length - 8 }}
							</span>
						</div>
						<div v-else class="mt-2 text-sm text-ink-gray-4">Not shared</div>
					</div>
				</template>
			</DocMetaPanel>

			<!-- shared-with-me: read-only info card (no docmeta — the docmeta read
			     gate covers owner/SM/DocShare only; child-table shares would 403) -->
			<div v-else-if="skill && !canEdit" class="m-5 space-y-3 rounded-md border p-4">
				<div class="flex items-center gap-2">
					<Avatar size="md" :label="sharedBy || 'another user'" />
					<div class="text-base font-medium text-ink-gray-8">{{ sharedBy || "Another user" }}</div>
				</div>
				<div class="text-sm text-ink-gray-5">
					Shared with you · read-only. Use /{{ form.skill_name }} in chat — you can’t edit or
					re-share it.
				</div>
				<div v-if="skill.modified" class="text-sm text-ink-gray-5">
					Updated {{ timeAgo(skill.modified) }}
				</div>
			</div>
		</template>

		<template #footer>
			<CommentsSection v-if="!isNew && canEdit && docmeta" :docmeta="docmeta" :can-comment="true" />
		</template>
	</DocPage>

	<ShareDialog
		v-model="shareOpen"
		:skill="{ name: id, skill_name: form.skill_name }"
		@saved="loadShares"
	/>
</template>

<script setup>
// Skill detail + create page (DESIGN-V3 §6.2): /skills/:id and /skills/new
// share this component (isNew prop). Explicit Save (D21) with dirty guard,
// read-only mode for shared-with-me skills, DocMetaPanel + child-table
// Shared-with block (#extra) + ShareDialog, sync pill on save/delete.
import { ref, reactive, computed, watch, shallowRef } from "vue"
import { useRouter, onBeforeRouteLeave } from "vue-router"
import {
	Button,
	Badge,
	Avatar,
	Tooltip,
	Dropdown,
	FormControl,
	Switch,
	toast,
	confirmDialog,
} from "frappe-ui"
import DocPage from "@/components/doc/DocPage.vue"
import DocSection from "@/components/doc/DocSection.vue"
import DocMetaPanel from "@/components/doc/DocMetaPanel.vue"
import CommentsSection from "@/components/doc/CommentsSection.vue"
import { useDocmeta } from "@/composables/useDocmeta"
import SyncPill from "./SyncPill.vue"
import ShareDialog from "./ShareDialog.vue"
import { timeAgo } from "@/utils/datetime"
import * as api from "@/api"

const props = defineProps({
	id: { type: String, default: "" },
	isNew: { type: Boolean, default: false },
})

const router = useRouter()
const DOCTYPE = "Jarvis Custom Skill"
const FIELDS = ["skill_name", "description", "instructions", "user_invocable", "enabled"]

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

// ── state ────────────────────────────────────────────────────────────────────
const skill = ref(null) // last server copy (null while new)
const loading = ref(false)
const loadError = ref("")
const saving = ref(false)

const form = reactive({
	skill_name: "",
	description: "",
	instructions: "",
	user_invocable: true,
	enabled: true,
})
let snapshot = { ...form } // saved-state copy for the dirty compare

const docmeta = shallowRef(null) // useDocmeta instance (own skills only)
const shares = ref([]) // [{name, full_name}]
const shareOpen = ref(false)
const syncPill = ref(null)

const canEdit = computed(() => props.isNew || !!(skill.value && skill.value.can_edit))
const readonly = computed(() => !canEdit.value || saving.value)
const sharedBy = computed(() => (skill.value && skill.value.shared_by) || "")

function normalize(v) {
	if (typeof v === "boolean") return v ? 1 : 0
	return v == null ? "" : v
}
const dirty = computed(() => {
	if (!canEdit.value) return false
	return FIELDS.some((k) => normalize(form[k]) !== normalize(snapshot[k]))
})

const pageTitle = computed(() =>
	props.isNew ? form.skill_name || "New Skill" : form.skill_name || props.id
)
const breadcrumbs = computed(() => [
	{ label: "Skills", route: { name: "SkillsList" } },
	props.isNew
		? { label: "New Skill", route: { name: "SkillNew" } }
		: { label: pageTitle.value, route: { name: "SkillDetail", params: { id: props.id } } },
])

const overflowOptions = [{ label: "Delete", onClick: () => confirmDelete() }]

// ── load / init (re-runs when /skills/new saves and replaces to /skills/:id) ─
function seed(data) {
	form.skill_name = data.skill_name || ""
	form.description = data.description || ""
	form.instructions = data.instructions || ""
	form.user_invocable = !!data.user_invocable
	form.enabled = !!data.enabled
	snapshot = { ...form }
}

let bypassGuard = false

async function init() {
	bypassGuard = false
	loadError.value = ""
	shares.value = []
	shareOpen.value = false
	docmeta.value = null
	if (props.isNew) {
		skill.value = null
		seed({ user_invocable: 1, enabled: 1 })
		return
	}
	if (!props.id) return
	loading.value = true
	try {
		const full = await api.getCustomSkill(props.id)
		skill.value = full
		seed(full)
		if (full.can_edit) {
			docmeta.value = useDocmeta(DOCTYPE, props.id)
			// created outside setup (async load / post-create replace) — fetch
			// explicitly rather than relying on the composable's auto-load
			if (docmeta.value && typeof docmeta.value.reload === "function") docmeta.value.reload()
			loadShares()
		}
	} catch (e) {
		loadError.value = errMsg(e)
	} finally {
		loading.value = false
	}
}

watch(() => [props.id, props.isNew], init, { immediate: true })

async function loadShares() {
	if (props.isNew || !props.id || !canEdit.value) return
	try {
		const res = (await api.getSkillShares(props.id)) || {}
		shares.value = res.users || []
	} catch (e) {
		// owner-only endpoint; best-effort
	}
}

// ── save / delete ────────────────────────────────────────────────────────────
async function save() {
	if (saving.value || !dirty.value) return
	const name = (form.skill_name || "").trim().toLowerCase()
	if (!name) {
		toast.error("Skill name is required.")
		return
	}
	saving.value = true
	try {
		const payload = {
			skill_name: name,
			description: form.description,
			instructions: form.instructions,
			user_invocable: form.user_invocable ? 1 : 0,
			enabled: form.enabled ? 1 : 0,
		}
		if (props.isNew) {
			const res = (await api.createCustomSkill(payload)) || {}
			const newName = (res.data && res.data.name) || ""
			snapshot = { ...form } // clean before navigating (leave guard)
			syncPill.value && syncPill.value.apply() // saving updates the assistant
			toast.success("Saved")
			if (newName) router.replace("/skills/" + newName)
		} else {
			// send only the changed fields
			const changed = {}
			for (const k of FIELDS) {
				if (normalize(form[k]) !== normalize(snapshot[k])) changed[k] = payload[k]
			}
			await api.updateCustomSkill({ name: props.id, ...changed })
			snapshot = { ...form }
			skill.value = { ...skill.value, ...payload }
			syncPill.value && syncPill.value.apply()
			toast.success("Saved")
		}
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		saving.value = false
	}
}

function confirmDelete() {
	confirmDialog({
		title: "Delete skill?",
		message: `Delete “${form.skill_name || props.id}”? It will be removed from your assistant.`,
		onConfirm: async ({ hideDialog }) => {
			try {
				await api.deleteCustomSkill(props.id)
				// reconcile the container; the list's pill picks up the pending state
				await api.applyCustomSkills().catch(() => {})
				bypassGuard = true
				hideDialog()
				toast.success("Skill deleted")
				router.push({ name: "SkillsList" })
			} catch (e) {
				toast.error(errMsg(e))
			}
		},
	})
}

// ── dirty guard (D21) ────────────────────────────────────────────────────────
onBeforeRouteLeave((to, from, next) => {
	if (bypassGuard || !dirty.value) return next()
	let decided = false
	confirmDialog({
		title: "Discard unsaved changes?",
		message: "Your edits to this skill will be lost.",
		onConfirm: ({ hideDialog }) => {
			decided = true
			hideDialog()
			next()
		},
		onCancel: () => {
			if (!decided) next(false)
		},
	})
})
</script>
