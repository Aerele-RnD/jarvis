import { ref, computed, onMounted, onBeforeUnmount } from "vue"
import { LIGHT_VARS, DARK_VARS, isDark } from "@/theme"

/**
 * Shared theme composable across ChatView, AiView, AccountView/AppSidebar, and
 * onboarding. The choice is sourced from and persisted to Frappe's per-user
 * desk_theme (via @/theme's boot + setUserTheme), so it roams across devices;
 * localStorage "jarvis-theme" is kept only as the pre-mount FOUC cache.
 *
 * The underlying refs are module-level singletons (not re-created per call)
 * so that when a view and a child component (e.g. AccountView + AppSidebar)
 * both call useTheme() on the same page, toggling in one instantly re-themes
 * the other - the browser's "storage" event only fires for *other* tabs, so
 * per-instance refs would otherwise fall out of sync within a single page.
 *
 * Exposes: pref, prefersDark, effectiveDark, paletteVars, setTheme, toggleTheme.
 */
// Seed from Frappe's native per-user desk_theme (booted as window.jarvis_desk_theme;
// see @/theme). localStorage "jarvis-theme" is now only the pre-mount FOUC cache
// that index.html reads — not the source of truth — so the choice roams per-user.
const _DESK_TO_PREF = { Light: "light", Dark: "dark", Automatic: "system" }
let _seed = "system"
try { _seed = _DESK_TO_PREF[window.jarvis_desk_theme] || "system" } catch (e) { /* boot missing → system */ }
const pref = ref(_seed)
const prefersDark = ref(false)
const effectiveDark = computed(() => isDark(pref.value, prefersDark.value))
const paletteVars = computed(() => (effectiveDark.value ? DARK_VARS : LIGHT_VARS))

function setTheme(t) {
	pref.value = t
	// Keep the FOUC cache (index.html's pre-mount script reads this key)...
	try { localStorage.setItem("jarvis-theme", t) } catch (e) {
		/* private mode / storage disabled - keep the in-memory choice */
	}
	// ...and persist to the roaming source of truth (User.desk_theme),
	// fire-and-forget: the in-memory pref already drives the UI.
	import("@/api").then(({ setUserTheme }) => setUserTheme(t)).catch(() => {})
}
// Cycle light → dark → system so "follow system" stays reachable (matches @/theme).
const _THEME_CYCLE = { light: "dark", dark: "system", system: "light" }
function toggleTheme() { setTheme(_THEME_CYCLE[pref.value] || "dark") }

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
