// Shared theme palette — consumed by ChatView.vue and AiView.vue.
// Extracted so both views stay visually consistent without duplicating vars.
export const LIGHT_VARS = {
	"--surface": "#ffffff", "--surface-1": "#f7f7f8", "--surface-2": "#f1f1f3", "--surface-3": "#ececef",
	"--border": "#e8e8ec", "--border-2": "#dfdfe4",
	"--text": "#171717", "--text-2": "#4a4a4f", "--text-3": "#83838b",
	"--blue": "#171717", "--blue-bg": "#eff4ff", "--blue-bd": "#d6e2fb",
	"--green": "#16a34a", "--green-bg": "#edf8f0", "--green-bd": "#cdeed8",
	"--red": "#dc2626", "--red-bg": "#fdf0ef", "--red-bd": "#f5d4d1",
	"--amber": "#d97706", "--amber-bg": "#fdf6ec", "--amber-bd": "#f3e2c2",
}
// Dark = "Refined Indigo" (chosen 2026-07-02): neutral charcoal surfaces with a
// crisper indigo accent; the brand mark gets an indigo→violet gradient.
export const DARK_VARS = {
	"--surface": "#16161a", "--surface-1": "#1d1d22", "--surface-2": "#26262d", "--surface-3": "#30303a",
	"--border": "#2c2c34", "--border-2": "#3a3a45",
	"--text": "#ededf2", "--text-2": "#b6b6c0", "--text-3": "#7e7e8a",
	"--blue": "#6e8bff", "--blue-bg": "#1e2749", "--blue-bd": "#34437a",
	"--green": "#34d399", "--green-bg": "#15271f", "--green-bd": "#214b38",
	"--red": "#f87171", "--red-bg": "#2a1818", "--red-bd": "#4a2a2a",
	"--amber": "#fbbf24", "--amber-bg": "#2a2315", "--amber-bd": "#4a3d1f",
}

/** Returns true when the effective theme should be dark. */
export function isDark(pref, prefersDark) {
	return pref === "dark" || (pref === "system" && prefersDark)
}
