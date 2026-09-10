import { describe, it, expect, beforeEach } from "vitest";
import {
	sessionFeedbackOpen,
	sessionFeedbackConversation,
	openSessionFeedback,
	closeSessionFeedback,
} from "./sessionFeedbackGate";

describe("sessionFeedbackGate", () => {
	beforeEach(() => {
		sessionFeedbackOpen.value = false;
		sessionFeedbackConversation.value = null;
	});

	it("openSessionFeedback sets the conversation and opens the dialog", () => {
		openSessionFeedback("conv-123");
		expect(sessionFeedbackOpen.value).toBe(true);
		expect(sessionFeedbackConversation.value).toBe("conv-123");
	});

	it("closeSessionFeedback closes without clearing the conversation", () => {
		openSessionFeedback("conv-123");
		closeSessionFeedback();
		expect(sessionFeedbackOpen.value).toBe(false);
		expect(sessionFeedbackConversation.value).toBe("conv-123");
	});
});
