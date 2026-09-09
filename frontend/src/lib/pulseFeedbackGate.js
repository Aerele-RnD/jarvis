// Periodic business-pulse survey. Unlike sessionFeedbackGate, this one owns
// its own trigger check (pulse_context is cheap and self-gating -- see spec
// Performance review), so callers just invoke maybeOpenPulseFeedback() once
// per chat open rather than passing a precomputed condition.
import { ref } from "vue";
import { pulseContext } from "@/api";

export const pulseFeedbackOpen = ref(false);
export const pulseFeedbackContext = ref(null); // {period_label, period_key, features_offered}

export async function maybeOpenPulseFeedback() {
	try {
		const ctx = await pulseContext();
		if (ctx && ctx.due) {
			pulseFeedbackContext.value = ctx;
			pulseFeedbackOpen.value = true;
		}
	} catch (e) {
		/* offline or admin unreachable -- skip silently, try again next open */
	}
}

export function closePulseFeedback() {
	pulseFeedbackOpen.value = false;
}
