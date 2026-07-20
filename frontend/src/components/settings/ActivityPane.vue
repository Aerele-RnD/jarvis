<template>
	<div class="jv-settings-body">
		<div class="jv-set-sec">Recent tool runs</div>
		<div v-if="!recentActivity.length" class="jv-set-empty">
			No tool activity in this chat yet.
		</div>
		<div v-for="(a, i) in recentActivity" :key="i" class="jv-act">
			<div class="jv-act-top">
				<svg
					width="13"
					height="13"
					viewBox="0 0 24 24"
					fill="none"
					stroke="var(--text-3)"
					stroke-width="1.8"
					stroke-linecap="round"
					stroke-linejoin="round"
				>
					<path
						d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 1 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"
					/>
				</svg>
				<span>{{ a.tools }} tool{{ a.tools === 1 ? "" : "s" }}</span>
				<span class="jv-act-ms">{{ (a.ms / 1000).toFixed(1) }}s</span>
			</div>
			<div v-if="a.names.length" class="jv-act-names">{{ a.names.join(" · ") }}</div>
		</div>
	</div>
</template>

<script setup>
import { computed } from "vue";
import { useShellStore } from "@/stores/shell";

const shell = useShellStore();
const recentActivity = computed(() => shell.chatContext?.sessionStats?.recentActivity || []);
</script>
