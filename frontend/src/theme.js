// Shared Jarvis theme: the palette CSS variables + a composable that tracks
// the per-device theme choice (localStorage "jarvis-theme": light | dark |
// system) and the OS color scheme.
//
// v3 (DESIGN-V3 §2.5 / D34): state is a MODULE-SCOPE singleton so the shell
// (UserMenu toggle), ChatView (header toggle + settings Appearance tab) and
// the feature pages all share one live theme. applyTheme() additionally
// bridges to frappe-ui by setting `data-theme` on <html> (the preset's
// darkMode selector) and `color-scheme` on :root, so frappe-ui components and
// the jv-* chat surface flip together.
import { ref, computed, watch } from "vue"

export const LIGHT_VARS = {
	"--surface": "#ffffff", "--surface-1": "#f7f7f8", "--surface-2": "#f1f1f3", "--surface-3": "#ececef",
	"--border": "#e8e8ec", "--border-2": "#dfdfe4",
	"--text": "#171717", "--text-2": "#4a4a4f", "--text-3": "#6d6d76",
	"--blue": "#4f46e5", "--blue-bg": "#eff4ff", "--blue-bd": "#d6e2fb", "--link": "#1579d0",
	"--green": "#16a34a", "--green-bg": "#edf8f0", "--green-bd": "#cdeed8",
	"--red": "#dc2626", "--red-bg": "#fdf0ef", "--red-bd": "#f5d4d1",
	"--amber": "#d97706", "--amber-bg": "#fdf6ec", "--amber-bd": "#f3e2c2",
}
// Dark = "Refined Indigo": neutral charcoal surfaces with a crisper indigo accent.
export const DARK_VARS = {
	"--surface": "#16161a", "--surface-1": "#1d1d22", "--surface-2": "#26262d", "--surface-3": "#30303a",
	"--border": "#2c2c34", "--border-2": "#3a3a45",
	"--text": "#ededf2", "--text-2": "#b6b6c0", "--text-3": "#7e7e8a",
	"--blue": "#6e8bff", "--blue-bg": "#1e2749", "--blue-bd": "#34437a", "--link": "#6e8bff",
	"--green": "#34d399", "--green-bg": "#15271f", "--green-bd": "#214b38",
	"--red": "#f87171", "--red-bg": "#2a1818", "--red-bd": "#4a2a2a",
	"--amber": "#fbbf24", "--amber-bg": "#2a2315", "--amber-bd": "#4a3d1f",
}

/** Returns true when the effective theme should be dark. (Kept for the
 * pre-v3 useTheme composable that Account/Onboarding/Monitor still use.) */
export function isDark(pref, prefersDark) {
	return pref === "dark" || (pref === "system" && prefersDark)
}

// ---- module-scope singleton state ------------------------------------------
let _stored = "system"
try { _stored = localStorage.getItem("jarvis-theme") || "system" } catch (e) { /* private mode */ }
const theme = ref(_stored)
const prefersDark = ref(false)

const effectiveDark = computed(
	() => theme.value === "dark" || (theme.value === "system" && prefersDark.value),
)
const paletteVars = computed(() => (effectiveDark.value ? DARK_VARS : LIGHT_VARS))

function applyTheme() {
	if (typeof document === "undefined") return
	const dark = effectiveDark.value
	document.documentElement.setAttribute("data-theme", dark ? "dark" : "light")
	document.documentElement.style.colorScheme = dark ? "dark" : "light"
}

let _started = false
function _start() {
	if (_started || typeof window === "undefined") return
	_started = true
	const mq = window.matchMedia("(prefers-color-scheme: dark)")
	prefersDark.value = mq.matches
	mq.addEventListener("change", (e) => { prefersDark.value = e.matches })
	// Singleton watcher (never stopped - lives for the page's lifetime).
	watch(effectiveDark, applyTheme)
	applyTheme()
}

function setTheme(t) {
	theme.value = t
	try { localStorage.setItem("jarvis-theme", t) } catch (e) { /* keep in-memory */ }
	applyTheme()
}
// Quick toggle: flip light/dark (drops out of 'system').
function toggleTheme() { setTheme(effectiveDark.value ? "light" : "dark") }

export function useJarvisTheme() {
	_start()
	return { theme, effectiveDark, paletteVars, setTheme, toggleTheme }
}
