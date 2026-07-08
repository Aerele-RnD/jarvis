<template>
	<Dropdown :options="menuOptions">
		<template #trigger="{ open }">
			<button
				class="flex h-12 items-center rounded-md py-2 duration-300 ease-in-out"
				:class="
					isCollapsed
						? 'w-auto px-0'
						: open
							? 'w-full px-2 bg-surface-white shadow-sm'
							: 'w-full px-2 hover:bg-surface-gray-3'
				"
				aria-label="Jarvis menu"
			>
				<!-- the jarvis gradient mark, 28×28 rounded -->
				<span
					class="grid h-7 w-7 shrink-0 place-items-center rounded-[7px]"
					style="background: linear-gradient(135deg, #6e8bff, #8b5cf6)"
				>
					<svg width="16" height="16" viewBox="0 0 24 24" fill="#fff">
						<path d="M12 2.5 L14 10 L21.5 12 L14 14 L12 21.5 L10 14 L2.5 12 L10 10 Z" />
					</svg>
				</span>
				<div
					class="flex flex-1 flex-col overflow-hidden text-left duration-300 ease-in-out"
					:class="isCollapsed ? 'ml-0 w-0 opacity-0' : 'ml-2 w-auto opacity-100'"
				>
					<div class="truncate text-base font-medium leading-none text-ink-gray-9">Jarvis</div>
					<div class="mt-1 truncate text-sm text-ink-gray-7">{{ fullName }}</div>
				</div>
				<FeatherIcon
					v-if="!isCollapsed"
					name="chevron-down"
					class="h-4 w-4 shrink-0 text-ink-gray-5"
				/>
			</button>
		</template>
	</Dropdown>
</template>

<script setup>
// Sidebar header (DESIGN-V3 §3.2.1): brand + session user, HD's UserMenu
// pattern. Dropdown: Settings (D9) · Switch to Desk · Toggle theme · Log out.
import { computed, inject } from "vue"
import { useRouter } from "vue-router"
import { Dropdown, FeatherIcon } from "frappe-ui"
import { useShellStore } from "@/stores/shell"
import { useJarvisTheme } from "@/theme"

defineProps({
	isCollapsed: { type: Boolean, default: false },
})

const store = useShellStore()
const router = useRouter()
const session = inject("$session")
const { effectiveDark, toggleTheme } = useJarvisTheme()

function cookie(name) {
	// URLSearchParams already percent-decodes; decoding AGAIN throws URIError
	// when the display name contains a literal '%' (stored as %25 → '%'),
	// blanking the whole shell - same bug main fixed in lib/user.js (0d19e7c).
	return new URLSearchParams(document.cookie.split("; ").join("&")).get(name)
}
const fullName = cookie("full_name") || session.user || "User"

const menuOptions = computed(() => [
	{
		group: "Menu",
		hideLabel: true,
		items: [
			{ label: "Settings", icon: "settings", onClick: () => store.openSettings(router) },
			// Account/Monitor ship on main (llm-proxy UI) - the routes exist only
			// once this branch merges with it, so gate on the router. Monitor is
			// SM-only there; www/jarvis.py (main side) boots is_system_manager.
			...(router.hasRoute("Account")
				? [{ label: "Account", icon: "user", onClick: () => router.push({ name: "Account" }) }]
				: []),
			...(router.hasRoute("Monitor") && window.is_system_manager !== false
				? [{ label: "Monitor", icon: "activity", onClick: () => router.push({ name: "Monitor" }) }]
				: []),
			{
				label: "Switch to Desk",
				icon: "grid",
				onClick: () => {
					window.location.href = "/app"
				},
			},
			{
				label: "Toggle theme",
				icon: effectiveDark.value ? "sun" : "moon",
				onClick: () => toggleTheme(),
			},
		],
	},
	{
		group: "Danger",
		hideLabel: true,
		items: [{ label: "Log out", icon: "log-out", theme: "red", onClick: () => session.logout() }],
	},
])
</script>
