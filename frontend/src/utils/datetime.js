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
