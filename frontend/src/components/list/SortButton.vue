<template>
	<div class="flex items-center">
		<Button
			v-if="!isDefault"
			:icon="sort.dir === 'asc' ? 'arrow-up' : 'arrow-down'"
			class="rounded-r-none border-r"
			:tooltip="sort.dir === 'asc' ? 'Ascending' : 'Descending'"
			@click="toggleDir"
		/>
		<Popover placement="bottom-end">
			<template #target="{ togglePopover }">
				<Button
					v-if="isDefault"
					label="Sort"
					iconLeft="bar-chart-2"
					@click="togglePopover()"
				/>
				<Button
					v-else
					:label="fieldLabel"
					class="rounded-l-none"
					@click="togglePopover()"
				/>
			</template>
			<template #body="{ close }">
				<div
					class="my-2 min-w-60 rounded-lg bg-surface-modal p-2 shadow-2xl ring-1 ring-black ring-opacity-5"
				>
					<FormControl
						type="select"
						label="Sort by"
						:options="sortOptions"
						:modelValue="sort.field || defaultSort.field || ''"
						@update:modelValue="(v) => pickField(v, close)"
					/>
					<div class="mt-2 flex justify-end border-t pt-2">
						<Button
							variant="ghost"
							label="Clear Sort"
							class="!text-ink-gray-5"
							@click="reset(close)"
						/>
					</div>
				</div>
			</template>
		</Popover>
		<Button
			v-if="!isDefault"
			variant="ghost"
			icon="x"
			:tooltip="'Reset sort'"
			@click="reset()"
		/>
	</div>
</template>

<script setup>
// SortButton - single field + direction (DESIGN-V3 §5.4, D15): plain "Sort"
// button at the page default; split button (asc/desc toggle + field label +
// ghost x reset) once a non-default sort is active. Emits update:sort {field, dir}.
import { computed } from "vue";
import { Popover, Button, FormControl } from "frappe-ui";

const props = defineProps({
	sortOptions: { type: Array, default: () => [] }, // [{label, value}]
	sort: { type: Object, default: () => ({ field: "", dir: "" }) },
	defaultSort: { type: Object, default: () => ({ field: "", dir: "" }) },
});

const emit = defineEmits(["update:sort"]);

const isDefault = computed(
	() =>
		(props.sort.field || "") === (props.defaultSort.field || "") &&
		(props.sort.dir || "") === (props.defaultSort.dir || "")
);

const fieldLabel = computed(() => {
	const opt = (props.sortOptions || []).find((o) => o.value === props.sort.field);
	return (opt && opt.label) || props.sort.field || "Sort";
});

function toggleDir() {
	emit("update:sort", {
		field: props.sort.field,
		dir: props.sort.dir === "asc" ? "desc" : "asc",
	});
}

function pickField(field, close) {
	if (!field) return;
	emit("update:sort", { field, dir: props.sort.dir || props.defaultSort.dir || "asc" });
	if (close) close();
}

function reset(close) {
	emit("update:sort", {
		field: props.defaultSort.field || "",
		dir: props.defaultSort.dir || "",
	});
	if (close) close();
}
</script>
