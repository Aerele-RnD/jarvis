// Agents-page API additions (DESIGN-V3 §8.4). `src/api.js` is frozen - new
// endpoints get thin wrappers in per-feature modules under src/api/.
import { call } from "frappe-ui"

// §8.3 - one agent's listing + THIS owner's installation (or null) for the
// detail page. -> { ...listing fields, allowed_roles, allowed: 0|1,
//   installation: {name, enabled, installed_version, config, schedule_*,
//   next_run_at, last_run_at, sync_status} | null, install_count: int,
//   all_roles: [str] (present only for System Manager - the Admin-tab signal) }
export const getAgent = (agent_slug) =>
	call("jarvis.chat.agents_api.get_agent", { agent_slug })

// ── Paginated agent lists (envelope {rows, total, has_more, start, page_length}) ─
// These take a tab/category/sort shape (not api.js `_page`'s filters/sort_field
// pair), matching the marketplace mental model: a tab strip, a category select,
// and a single sort choice. Page components wrap useListPage with an adapter
// fetchFn that maps its ({search, filters, sort_field, ...}) call onto these.
const AG = "jarvis.chat.agents_api."

// tab: featured|available|installed · sort: installs|updated|name
export const listAgentsPage = (p = {}) =>
	call(AG + "list_agents_page", {
		tab: p.tab || "available",
		category: p.category || "",
		sort: p.sort || "installs",
		search: p.search || "",
		start: p.start || 0,
		page_length: p.page_length || 20,
	})

// Owner-scoped runs for one agent (the two-pane Runs rail). sort: recent.
export const listRunsPage = (p = {}) =>
	call(AG + "list_runs_page", {
		agent: p.agent || "",
		status: p.status || "",
		search: p.search || "",
		sort: p.sort || "recent",
		start: p.start || 0,
		page_length: p.page_length || 20,
	})

// Owner-scoped activity feed (install/uninstall/enable/disable/run events).
export const listAgentActivityPage = (p = {}) =>
	call(AG + "list_agent_activity_page", {
		agent: p.agent || "",
		action: p.action || "",
		search: p.search || "",
		start: p.start || 0,
		page_length: p.page_length || 20,
	})

// Seed a new conversation from a finding and land the user in live chat.
// -> { ok, conversation, run_id, reason }
export const takeFindingToChat = (finding) =>
	call(AG + "take_finding_to_chat", { finding })
