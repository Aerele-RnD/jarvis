<template>
	<div class="jv-settings-body">
		<div class="jv-set-sec">Theme</div>
		<div class="jv-seg">
			<button :class="{ on: theme === 'light' }" @click="setTheme('light')">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
				Light
			</button>
			<button :class="{ on: theme === 'dark' }" @click="setTheme('dark')">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
				Dark
			</button>
			<button :class="{ on: theme === 'system' }" @click="setTheme('system')">
				<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></svg>
				System
			</button>
		</div>
		<div class="jv-set-hint">{{ theme === "system" ? (effectiveDark ? "Following system · dark" : "Following system · light") : "Saved on this device" }}</div>

		<div class="jv-set-sec" style="margin-top:22px;">About</div>
		<div class="jv-set-row"><span>Jarvis</span><b>ERPNext Assistant</b></div>
	</div>
</template>

<script setup>
import { useJarvisTheme } from "@/theme"

const { theme, effectiveDark, setTheme } = useJarvisTheme()
</script>
