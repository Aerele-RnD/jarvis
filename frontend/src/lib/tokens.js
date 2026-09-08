/** Shared token-count formatting for the context meter and usage panes. */

/** "42000" -> "42k", "1500000" -> "1.5M". Strips a trailing ".0" so a round
 * thousand/million reads "42k" rather than "42.0k". */
export function fmtTokens(n) {
	n = Number(n || 0);
	if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
	if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "k";
	return String(n);
}

/** What GeneralPane and UsagePane's "This chat" / "Context" row shows, from
 * get_usage()'s per-conversation `usage.context` block. `fresh` is a live
 * reading; otherwise the context has not been measured yet. */
export function contextReading(usage) {
	const context = usage && usage.context;
	const fresh = !!(context && context.fresh);
	return {
		fresh,
		text: fresh
			? `${fmtTokens(context.used)} of ${fmtTokens(context.capacity)} context in use`
			: "Not measured yet",
	};
}

/** Windows the per-user token cap can apply to (Jarvis User Settings.limit_period),
 * as frappe-ui select options. The server owns the enum; this mirrors it. */
export const LIMIT_PERIOD_OPTIONS = [
	{ label: "All time", value: "All time" },
	{ label: "Daily", value: "Daily" },
	{ label: "Weekly", value: "Weekly" },
	{ label: "Monthly", value: "Monthly" },
];

const WINDOW_LABEL = { Daily: "today", Weekly: "this week", Monthly: "this month" };

/** What a token cap is measured against, from a measured-usage / admin row:
 * the cumulative total for an all-time cap, else the current window's
 * `period_tokens` (already 0 server-side when the window has rolled). */
export function limitWindow(row) {
	const label = WINDOW_LABEL[row && row.limit_period];
	if (!label) return { used: Number((row && row.total_tokens) || 0), label: "all time" };
	return { used: Number(row.period_tokens || 0), label };
}
