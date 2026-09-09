// Once-per-session feedback popup, opened the same way WhatsNewDialog is:
// a shared ref set from wherever the trigger condition is detected
// (ChatView.vue, after a reply crosses the turn threshold), watched by the
// dialog component below. Server-side "already asked" (session_feedback_asked_at)
// is the real guarantee; this ref only controls whether it's ON SCREEN right now.
import { ref } from "vue";

export const sessionFeedbackOpen = ref(false);
export const sessionFeedbackConversation = ref(null);

export function openSessionFeedback(conversation) {
	sessionFeedbackConversation.value = conversation;
	sessionFeedbackOpen.value = true;
}

export function closeSessionFeedback() {
	sessionFeedbackOpen.value = false;
}
