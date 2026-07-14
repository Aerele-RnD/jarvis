// Frappe hands back naive datetimes in the site timezone ("2026-07-13 14:02:11").
// Safari refuses to parse that form, so normalise before constructing a Date --
// otherwise every timestamp on iOS reads "Invalid Date".
export function relativeTime(value) {
	if (!value) return ""
	const then = new Date(String(value).replace(" ", "T"))
	if (Number.isNaN(then.getTime())) return ""

	const secs = Math.max(0, (Date.now() - then.getTime()) / 1000)
	if (secs < 60) return "just now"
	const mins = Math.floor(secs / 60)
	if (mins < 60) return `${mins}m ago`
	const hours = Math.floor(mins / 60)
	if (hours < 24) return `${hours}h ago`
	const days = Math.floor(hours / 24)
	if (days < 7) return `${days}d ago`
	return then.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}
