import { reactive } from "vue";
import * as api from "./api";

// One small shared store: the conversation list is read by the chats screen and
// the drawer, and written by the chat screen (a reply retitles the chat). The
// drawer is opened from whichever screen is on top.
export const store = reactive({
	drawerOpen: false,
	conversations: [],
	loaded: false,

	async loadConversations() {
		try {
			const rows = await api.listConversations();
			this.conversations = Array.isArray(rows) ? rows : [];
		} catch (e) {
			// Offline or a dropped bench: keep whatever is on screen rather than
			// blanking the list under the user.
			console.error("Jarvis PWA: failed to load conversations", e);
		} finally {
			this.loaded = true;
		}
	},

	// The worker titles a chat asynchronously, after the first real turn.
	applyRename(id, title) {
		const row = this.conversations.find((c) => c.name === id);
		if (row) row.title = title;
	},
});
