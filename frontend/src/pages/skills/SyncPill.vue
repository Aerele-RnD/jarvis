<template>
	<div v-if="pending || failed" class="inline-flex items-center gap-2">
		<Tooltip v-if="pending" text="Updating your assistant… (restarts briefly, ~30s)">
			<Badge theme="orange" variant="subtle">
				<template #prefix>
					<LoadingIndicator class="size-3" />
				</template>
				Applying skills…
			</Badge>
		</Tooltip>
		<template v-else>
			<Tooltip :text="failureReason || 'Applying skills to your assistant failed.'">
				<Badge theme="red" variant="subtle" label="Apply failed" />
			</Tooltip>
			<Button variant="ghost" label="Retry" :loading="applying" @click="apply" />
		</template>
	</div>
</template>

<script setup>
// SyncPill — shared skills-apply status pill (DESIGN-V3 §5.6 + §6.2): shown by
// the Skills list banner and the skill detail header. Polls
// getCustomSkillsSyncStatus every 3s while an apply is pending; a failed apply
// turns the pill red with a Retry ghost button (applyCustomSkills).
// Exposed API:
//   apply()    — trigger an apply then poll (save/delete flows; those
//                endpoints don't enqueue an apply on their own)
//   checkNow() — read the status and poll if pending (bulk delete — the
//                server already enqueued the apply, §8.3)
import { ref, computed, onMounted, onBeforeUnmount } from "vue"
import { Badge, Button, Tooltip, LoadingIndicator, toast } from "frappe-ui"
import * as api from "@/api"

function errMsg(e) {
	return (e && ((e.messages && e.messages[0]) || e.message)) || "Something went wrong."
}

const status = ref("") // last_sync_status: "", "pending: …", "ok …", "failed: …"
const pending = ref(false)
const applying = ref(false)

const failed = computed(() => (status.value || "").startsWith("failed"))
const failureReason = computed(() =>
	failed.value ? (status.value || "").replace(/^failed:?/, "").trim() : ""
)

let timer = null
function startPoll() {
	if (timer) return
	timer = setInterval(async () => {
		await load()
		if (!pending.value) stopPoll()
	}, 3000)
}
function stopPoll() {
	if (timer) {
		clearInterval(timer)
		timer = null
	}
}

async function load() {
	try {
		const s = (await api.getCustomSkillsSyncStatus()) || {}
		status.value = s.last_sync_status || ""
		pending.value = !!s.pending
	} catch (e) {
		// best-effort: a transient status failure must not break the page
	}
}

async function checkNow() {
	await load()
	if (pending.value) startPoll()
}

async function apply() {
	if (applying.value) return
	applying.value = true
	try {
		await api.applyCustomSkills()
		status.value = "pending: applying skills"
		pending.value = true
		startPoll()
	} catch (e) {
		toast.error(errMsg(e))
	} finally {
		applying.value = false
	}
}

onMounted(() => checkNow())
onBeforeUnmount(() => stopPoll())

defineExpose({ apply, checkNow, pending })
</script>
