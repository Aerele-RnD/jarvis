import { ref, computed, onMounted, onBeforeUnmount } from "vue"
import { LIGHT_VARS, DARK_VARS, isDark } from "@/theme"

/**
 * Shared theme composable — single source of truth for the "jarvis-theme"
 * localStorage preference across ChatView, AiView, AccountView/AppSidebar,
 * and any future views.
 *
 * The underlying refs are module-level singletons (not re-created per call)
 * so that when a view and a child component (e.g. AccountView + AppSidebar)
 * both call useTheme() on the same page, toggling in one instantly re-themes
 * the other — the browser's "storage" event only fires for *other* tabs, so
 * per-instance refs would otherwise fall out of sync within a single page.
 *
 * Exposes: pref, prefersDark, effectiveDark, paletteVars, setTheme, toggleTheme.
 */
const pref = ref(localStorage.getItem("jarvis-theme") || "system")
const prefersDark = ref(false)
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

function onColorScheme(e) { prefersDark.value = e.matches }
// Sync across tabs: when another tab writes "jarvis-theme" to localStorage,
// window.storage fires here so all views stay in lock-step.
function onStorage(e) {
	if (e.key === "jarvis-theme" && e.newValue) pref.value = e.newValue
}

let _mq = null
let _listeners = 0

export function useTheme() {
	onMounted(() => {
		if (_listeners === 0) {
			_mq = window.matchMedia("(prefers-color-scheme: dark)")
			prefersDark.value = _mq.matches
			_mq.addEventListener("change", onColorScheme)
			window.addEventListener("storage", onStorage)
		}
		_listeners++
	})
	onBeforeUnmount(() => {
		_listeners--
		if (_listeners === 0) {
			_mq?.removeEventListener("change", onColorScheme)
			window.removeEventListener("storage", onStorage)
			_mq = null
		}
	})

	return { pref, prefersDark, effectiveDark, paletteVars, setTheme, toggleTheme }
}
