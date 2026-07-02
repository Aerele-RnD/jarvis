import { ref, computed, onMounted, onBeforeUnmount } from "vue"
import { LIGHT_VARS, DARK_VARS, isDark } from "@/theme"

/**
 * Shared theme composable — single source of truth for the "jarvis-theme"
 * localStorage preference across ChatView, AiView, and any future views.
 *
 * Exposes: pref, prefersDark, effectiveDark, paletteVars, setTheme, toggleTheme.
 */
export function useTheme() {
	const pref = ref(localStorage.getItem("jarvis-theme") || "system")
	const prefersDark = ref(false)
	let _mq = null

	function onColorScheme(e) { prefersDark.value = e.matches }

	// Sync across tabs: when another view writes "jarvis-theme" to localStorage,
	// window.storage fires here so both views stay in lock-step.
	function onStorage(e) {
		if (e.key === "jarvis-theme" && e.newValue) pref.value = e.newValue
	}

	const effectiveDark = computed(() => isDark(pref.value, prefersDark.value))
	const paletteVars = computed(() => (effectiveDark.value ? DARK_VARS : LIGHT_VARS))

	function setTheme(t) {
		pref.value = t
		try { localStorage.setItem("jarvis-theme", t) } catch (e) {
			/* private mode / storage disabled — keep the in-memory choice */
		}
	}
	// Quick toggle: flip between light and dark (drops out of 'system').
	function toggleTheme() { setTheme(effectiveDark.value ? "light" : "dark") }

	onMounted(() => {
		_mq = window.matchMedia("(prefers-color-scheme: dark)")
		prefersDark.value = _mq.matches
		_mq.addEventListener("change", onColorScheme)
		window.addEventListener("storage", onStorage)
	})
	onBeforeUnmount(() => {
		_mq?.removeEventListener("change", onColorScheme)
		window.removeEventListener("storage", onStorage)
	})

	return { pref, prefersDark, effectiveDark, paletteVars, setTheme, toggleTheme }
}
