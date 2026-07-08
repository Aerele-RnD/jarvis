// Per-surface renderer feature flag (R10). Default ON — the 3D graph is now the
// standard view (the old sigma/esbuild graph was retired). `localStorage.wg3d
// = "off"` remains a per-surface kill-switch for instant rollback; a surface may
// also force it via window.__wg3d.
export function renderer3dEnabled() {
	try {
		if (typeof localStorage !== "undefined") {
			const v = localStorage.getItem("wg3d");
			if (v === "on") return true;
			if (v === "off") return false;
		}
		if (typeof window !== "undefined" && window.__wg3d != null) return !!window.__wg3d;
	} catch (_) {
		/* privacy-mode storage access can throw */
	}
	return true;
}
