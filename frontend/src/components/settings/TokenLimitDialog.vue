<template>
	<Dialog v-model="show" :options="{ title }">
		<template #body-content>
			<div class="flex flex-col gap-4">
				<FormControl
					type="number"
					label="Limit (tokens)"
					v-model.number="limitDraft"
					:disabled="saving"
					placeholder="0 = unlimited"
				/>
				<FormControl
					v-if="!model"
					type="select"
					label="Window"
					:options="LIMIT_PERIOD_OPTIONS"
					v-model="periodDraft"
					:disabled="saving"
				/>
				<p class="text-p-sm text-ink-gray-5">{{ hint }}</p>
			</div>
		</template>
		<template #actions>
			<div class="flex items-center justify-end gap-2">
				<Button label="Cancel" :disabled="saving" @click="show = false" />
				<Button variant="solid" label="Save" :loading="saving" @click="save" />
			</div>
		</template>
	</Dialog>
</template>

<script setup>
// One editor for both caps in User usage: the per-user cap (limit + window)
// and a per-model monthly cap (limit only, when `model` is set). Same shape
// as the other settings dialogs: fields in the body, Cancel / Save below.
import { computed, ref, watch } from "vue";
import { Button, Dialog, FormControl, toast } from "frappe-ui";
import { LIMIT_PERIOD_OPTIONS } from "@/lib/tokens.js";
import { modelDisplayLabel } from "@/utils/usageModel";
import * as api from "@/api";
import { errHtml } from "@/lib/errors";

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	user: { type: String, required: true },
	userLabel: { type: String, default: "" },
	model: { type: String, default: "" },
	limit: { type: Number, default: 0 },
	period: { type: String, default: "All time" },
});
const emit = defineEmits(["update:modelValue", "saved"]);

const show = computed({
	get: () => props.modelValue,
	set: (v) => emit("update:modelValue", v),
});
const limitDraft = ref(props.limit);
const periodDraft = ref(props.period);
const saving = ref(false);
watch(
	() => props.modelValue,
	(open) => {
		if (!open) return;
		limitDraft.value = props.limit;
		periodDraft.value = props.period;
	}
);

const title = computed(() =>
	props.model
		? `Monthly limit · ${modelDisplayLabel(props.model)}`
		: `Token limit · ${props.userLabel || props.user}`
);
const hint = computed(() =>
	props.model
		? "0 = unlimited. Counts this month, resets on the 1st."
		: "0 = unlimited. Changing the window restarts it now."
);

async function save() {
	const val = Math.max(0, Math.round(Number(limitDraft.value) || 0));
	saving.value = true;
	try {
		const res = props.model
			? await api.adminSetUserModelLimit(props.user, props.model, val)
			: await api.adminSetUserLimit(props.user, val, periodDraft.value);
		if (res && res.ok === false) {
			toast.error(res.reason || "Could not update the limit.");
			return;
		}
		const d = (res && res.data) || {};
		emit("saved", {
			model: props.model,
			monthly_token_limit: d.monthly_token_limit != null ? d.monthly_token_limit : val,
			limit_period: d.limit_period || periodDraft.value,
		});
		toast.success("Limit updated");
		show.value = false;
	} catch (e) {
		toast.error(errHtml(e));
	} finally {
		saving.value = false;
	}
}
</script>
