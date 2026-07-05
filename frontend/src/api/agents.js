// Agents-page API additions (DESIGN-V3 §8.4). `src/api.js` is frozen — new
// endpoints get thin wrappers in per-feature modules under src/api/.
import { call } from "frappe-ui"

// §8.3 — one agent's listing + THIS owner's installation (or null) for the
// detail page. -> { ...listing fields, allowed_roles, allowed: 0|1,
//   installation: {name, enabled, installed_version, config, schedule_*,
//   next_run_at, last_run_at, sync_status} | null, install_count: int,
//   all_roles: [str] (present only for System Manager — the Admin-tab signal) }
export const getAgent = (agent_slug) =>
	call("jarvis.chat.agents_api.get_agent", { agent_slug })
