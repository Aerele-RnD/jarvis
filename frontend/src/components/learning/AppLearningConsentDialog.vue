<template>
	<Dialog
		:modelValue="modelValue"
		:options="{ title: dialogTitle, size: 'md' }"
		@update:modelValue="(v) => emit('update:modelValue', v)"
	>
		<template #body-content>
			<div class="flex flex-col gap-3 text-sm">
				<!-- mandatory amber banner (the ReviewTab apply-dialog idiom) -->
				<div
					class="flex items-start gap-2 rounded-lg border border-outline-amber-2 bg-surface-amber-1 px-3 py-2 text-ink-amber-3"
				>
					<FeatherIcon name="alert-triangle" class="mt-0.5 size-4 shrink-0" />
					<span class="font-medium">Token-intensive one-time analysis</span>
				</div>

				<p class="text-ink-gray-7">
					{{ agentName }} will analyze
					<span class="font-medium text-ink-gray-8">{{ appLine }}</span
					><template v-if="when"
						>, scheduled for
						<span class="font-medium text-ink-gray-8">{{
							exactDate(when)
						}}</span></template
					>.
				</p>

				<ul class="flex list-disc flex-col gap-1.5 pl-5 text-ink-gray-7">
					<li>
						This will consume a significant amount of your LLM budget - roughly
						proportional to the size of each app.
					</li>
					<li>
						Findings are written <b>directly</b> to your Org wiki without a review
						step.
					</li>
					<li>
						Useful functions may be added as org-wide skills - created
						<b>disabled</b> for your review; enable them from Skills after checking
						their instructions (you or a System Manager can manage them there).
					</li>
					<li>
						Only analyze apps whose code you trust - source code, including comments,
						influences the analysis.
					</li>
				</ul>
			</div>
		</template>
		<template #actions>
			<div class="flex items-center gap-2">
				<Button
					variant="solid"
					label="I understand - start analysis"
					:loading="loading"
					@click="emit('confirm')"
				/>
				<Button
					label="Cancel"
					:disabled="loading"
					@click="emit('update:modelValue', false)"
				/>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
// AppLearningConsentDialog - the MANDATORY consent step before any
// schedule_app_learning call (mirrors ReviewTab's amber-banner apply dialog).
// Dumb by design: it renders the warning + the selection recap and emits
// `confirm`; the owning card performs the API call (passing consent: 1),
// drives :loading, and closes the dialog on success - so the consent copy and
// the write stay in one reviewable place each.
import { computed } from "vue";
import { Button, Dialog, FeatherIcon } from "frappe-ui";
import { exactDate } from "@/utils/datetime";
import { agentName } from "@/branding";

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	// selected apps: [{app, title}] (title falls back to the app name)
	apps: { type: Array, default: () => [] },
	// "" = run now | naive SITE-timezone "YYYY-MM-DD HH:mm:ss" (already
	// converted by the card; exactDate renders it back in the viewer's zone)
	when: { type: String, default: "" },
	loading: { type: Boolean, default: false },
});
const emit = defineEmits(["update:modelValue", "confirm"]);

const dialogTitle = computed(
	() => `Analyze ${props.apps.length} app${props.apps.length === 1 ? "" : "s"}?`
);
const appLine = computed(() => props.apps.map((a) => a.title || a.app).join(", "));
</script>
