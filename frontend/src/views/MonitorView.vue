<template>
	<div class="jv-app" :class="{ 'jv-dark': dark }" :style="paletteVars"
		 style="display:flex;min-height:100vh;background:var(--surface);color:var(--text);">

		<AppSidebar />

		<main style="flex:1;min-width:0;overflow-y:auto;height:100vh;padding:28px 32px 60px;">
			<h1 style="font-size:20px;font-weight:600;margin:0 0 18px;">Usage</h1>
			<MonitorTab :dark="dark" />
		</main>
	</div>
</template>

<script setup>
import { useTheme } from "@/composables/useTheme"
import AppSidebar from "@/components/AppSidebar.vue"
import MonitorTab from "@/views/MonitorTab.vue"

// Theme — shared composable: honours "jarvis-theme" pref, cross-tab sync, OS live.
const { effectiveDark: dark, paletteVars } = useTheme()
</script>
