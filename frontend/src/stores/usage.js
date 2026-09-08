// The signed-in user's own token cap and usage, for the composer's UsagePill.
// One roaming source (Jarvis User Settings via get_my_settings); refreshed on
// chat open and after every completed turn, alongside the context ring.
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
