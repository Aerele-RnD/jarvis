// Shell-owned API wrappers (DESIGN-V3 §8.4). `src/api.js` is frozen — new
// endpoints get thin wrappers in per-feature modules under src/api/.
import { call } from "frappe-ui"

// D40 — title-only, paginated, owner-scoped conversation search (⌘K palette).
// -> { rows: [{name, title, starred, last_active_at}], total, has_more, start, page_length }
export const searchConversations = (params = {}) =>
	call("jarvis.chat.api.search_conversations", {
		search: params.search || "",
		start: params.start || 0,
		page_length: params.page_length || 20,
	})
