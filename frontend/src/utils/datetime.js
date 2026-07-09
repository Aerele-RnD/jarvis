// Shared server-datetime rendering. Frappe returns naive datetime strings in
// the SITE timezone; parsing them with new Date()/dayjs() treats them as
// browser-local and shows future-tense "in N minutes" for any viewer whose
// timezone differs from the site's. frappe-ui's dayjsLocal() parses in
// setConfig("systemTimezone") (fed from get_chat_ui_settings.time_zone in
// AppShell) and converts to the browser zone; without the config it falls
// back to plain dayjs() - today's behavior.
import { dayjsLocal } from "frappe-ui"

export function timeAgo(d) {
	return d ? dayjsLocal(String(d)).fromNow() : ""
}

export function exactDate(d) {
	return d ? dayjsLocal(String(d)).format("ddd, MMM D, YYYY h:mm A") : ""
}

export function formatDate(d, fmt) {
	return d ? dayjsLocal(String(d)).format(fmt || "MMM D, YYYY") : ""
}

// Day-bucket label for chat day separators, timezone-safe like the rest of this
// module. Accepts a naive site-tz string (creation/modified) or a browser Date /
// ms number (optimistic rows). "Today" / "Yesterday" / weekday within a week /
// "D MMMM" beyond.
export function dayLabel(d) {
	if (d == null || d === "") return ""
	const dj = dayjsLocal(d)
	if (!dj || typeof dj.isValid !== "function" || !dj.isValid()) return ""
	const diff = dayjsLocal().startOf("day").diff(dj.startOf("day"), "day")
	if (diff === 0) return "Today"
	if (diff === 1) return "Yesterday"
	if (diff > 1 && diff < 7) return dj.format("dddd")
	return dj.format("D MMMM")
}
