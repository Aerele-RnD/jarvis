// Skills-page API additions (DESIGN-V3 §8.4). `src/api.js` is frozen - new
// endpoints get thin wrappers in per-feature modules under src/api/.
import { call } from "frappe-ui";

// §8.3 - bulk delete of own skills. The server skips shared/not-owned rows
// with per-row reasons and enqueues ONE skills-apply at the end.
// -> { deleted: int, skipped: [{name, reason}] }
export const deleteCustomSkillsBulk = (names) =>
	call("jarvis.chat.custom_skills_api.delete_custom_skills_bulk", {
		names: JSON.stringify(Array.from(names || [])),
	});
