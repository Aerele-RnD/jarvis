<template>
	<div class="jv-app flex h-full flex-col overflow-hidden" :class="{ 'jv-dark': dark }" :style="paletteVars"
		 style="background:var(--surface);color:var(--text);">

		<!-- Shell-integrated header — no per-view sidebar; the app shell's Sidebar
		     owns navigation, same chrome as Agents / Skills / Macros / Account. -->
		<LayoutHeader>
			<template #left-header>
				<Breadcrumbs :items="[{ label: 'Usage', route: { name: 'Monitor' } }]" />
			</template>
		</LayoutHeader>

		<main style="flex:1;min-width:0;min-height:0;overflow-y:auto;padding:28px 32px 60px;">
			<MonitorTab :dark="dark" />
		</main>
	</div>
</template>

<script setup>
import { useTheme } from "@/composables/useTheme"
import { Breadcrumbs } from "frappe-ui"
import LayoutHeader from "@/components/LayoutHeader.vue"
import MonitorTab from "@/views/MonitorTab.vue"

// Theme — shared composable: honours "jarvis-theme" pref, cross-tab sync, OS live.
const { effectiveDark: dark, paletteVars } = useTheme()
</script>
