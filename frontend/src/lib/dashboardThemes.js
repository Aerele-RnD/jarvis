// Named render themes for dashboard canvases. The shell (buildSrcdoc) injects
// the selected theme as CSS variables + a small base stylesheet ahead of the
// dashboard's own styles, so the SAME generated HTML re-skins when the user
// switches themes: the skill instructs the agent to color everything with the
// --jd-* variables instead of hardcoding.
//
// Keys are lowercase (API/theme picker); the DocType stores the capitalized
// label ("Jarvis" | "Insight" | "Claude" | "Graphite") — use themeKey()/
// themeLabel() to convert. "Jarvis" is the product default: the app's own
// design language (design.md — gray-on-white, ink-gray scale, hairlines,
// near-black accent) so an unprompted dashboard looks native. The agent only
// deviates from the injected theme when the user explicitly asks about the
// design; otherwise the standard applies.

const VARS = (v) => `:root{
--jd-bg:${v.bg};--jd-surface:${v.surface};--jd-ink:${v.ink};--jd-heading:${
	v.heading || v.ink
};--jd-muted:${v.muted};
--jd-line:${v.line};--jd-accent:${v.accent};--jd-radius:10px;--jd-shadow:${v.shadow};
--jd-font:${v.font};--jd-font-display:${v.fontDisplay};
}`;

// Modest base rules only — layout stays the dashboard's job; these make an
// under-styled document look decent and re-skinnable. Injected BEFORE the
// dashboard's own <style>, so its rules win any conflict.
const BASE = `
html,body{background:var(--jd-bg);color:var(--jd-ink);font-family:var(--jd-font);margin:0;}
h1,h2,h3{font-family:var(--jd-font-display);color:var(--jd-heading,var(--jd-ink));}
table{border-collapse:collapse;width:100%;}
th{color:var(--jd-muted);font-weight:600;text-align:left;}
th,td{padding:8px 12px;border-bottom:1px solid var(--jd-line);}
section.slide{background:var(--jd-bg);}
`;

// System stack only: the sandbox's CSP is `font-src data:` with no network, so
// a webfont (Inter) can't load inside the canvas - claiming it would silently
// fall back anyway. The system sans matches design.md's own fallback chain.
const SANS = `-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif`;

export const THEMES = {
	jarvis: {
		key: "jarvis",
		label: "Jarvis",
		dark: false,
		accent: "#383838",
		// Gray-anchored, muted series colors — hue stays informational, the
		// near-black primary matches the app's solid-CTA gray (design.md §2.1).
		palette: [
			"#383838",
			"#5d78d1",
			"#4c9a7a",
			"#d9a53f",
			"#c25d5d",
			"#8a7bb8",
			"#5a99ae",
			"#a0693f",
		],
		css:
			VARS({
				bg: "#f8f8f8",
				surface: "#ffffff",
				ink: "#383838",
				heading: "#171717",
				muted: "#7c7c7c",
				line: "#ededed",
				accent: "#383838",
				shadow: "0 1px 2px rgba(0,0,0,.05)",
				font: SANS,
				fontDisplay: SANS,
			}) + BASE,
	},
	insight: {
		key: "insight",
		label: "Insight",
		dark: false,
		accent: "#2490ef",
		palette: [
			"#2490ef",
			"#25b885",
			"#f5a623",
			"#e24c4c",
			"#9b59b6",
			"#17a2b8",
			"#fd7e14",
			"#5856d6",
		],
		css:
			VARS({
				bg: "#f3f3f3",
				surface: "#ffffff",
				ink: "#1f272e",
				muted: "#6c7680",
				line: "#e2e2e2",
				accent: "#2490ef",
				shadow: "0 1px 2px rgba(25,39,52,.06)",
				font: SANS,
				fontDisplay: SANS,
			}) + BASE,
	},
	claude: {
		key: "claude",
		label: "Claude",
		dark: false,
		accent: "#d97757",
		palette: [
			"#d97757",
			"#7d9b76",
			"#dfa32e",
			"#6a9bcc",
			"#b0603f",
			"#8a7bb8",
			"#5c8a72",
			"#c2542e",
		],
		css:
			VARS({
				bg: "#faf9f5",
				surface: "#ffffff",
				ink: "#3d3929",
				muted: "#83827d",
				line: "#e8e6dc",
				accent: "#d97757",
				shadow: "0 1px 2px rgba(61,57,41,.06)",
				font: SANS,
				fontDisplay: `Georgia,"Times New Roman",serif`,
			}) + BASE,
	},
	graphite: {
		key: "graphite",
		label: "Graphite",
		dark: true,
		accent: "#8ab4f8",
		palette: [
			"#8ab4f8",
			"#4ade80",
			"#fbbf24",
			"#f87171",
			"#c084fc",
			"#22d3ee",
			"#fb923c",
			"#a3e635",
		],
		css:
			VARS({
				bg: "#191919",
				surface: "#222222",
				ink: "#ececec",
				muted: "#9a9a9a",
				line: "#333333",
				accent: "#8ab4f8",
				shadow: "none",
				font: SANS,
				fontDisplay: SANS,
			}) + BASE,
	},
};

export const DEFAULT_THEME = "jarvis";

export const THEME_OPTIONS = Object.values(THEMES).map((t) => ({
	key: t.key,
	label: t.label,
}));

// DocType stores the capitalized label; the SPA works in lowercase keys.
export function themeKey(label) {
	const k = String(label || "").toLowerCase();
	return THEMES[k] ? k : DEFAULT_THEME;
}

export function themeLabel(key) {
	return (THEMES[themeKey(key)] || THEMES[DEFAULT_THEME]).label;
}
