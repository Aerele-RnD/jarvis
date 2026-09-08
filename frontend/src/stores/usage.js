// The signed-in user's own token cap and usage, for the composer's UsagePill.
// Fed by the context-meter payload the chat already fetches on open and after
// every completed turn (takeUsage), so the pill costs no request of its own; a
// brand-new chat with no conversation yet loads it once from settings.
import { ref } from "vue";
import * as api from "@/api";

export const myUsage = ref(null);

const FIELDS = ["monthly_token_limit", "limit_period", "period_tokens", "total_tokens"];

export async function loadMyUsage() {
	try {
		const r = await api.getMySettings();
		const d = (r && r.data) || null;
		if (!d) return;
		myUsage.value = Object.fromEntries(FIELDS.map((k) => [k, d[k]]));
	} catch {
		/* the pill is best-effort; a failed read keeps the last reading */
	}
}

/** Take the cap reading off a get_conversation_context payload. A payload
 * without one (older server, error path) keeps the last reading. */
export function takeUsage(context) {
	const u = context && context.usage;
	if (!u) return;
	myUsage.value = Object.fromEntries(FIELDS.map((k) => [k, u[k]]));
}
