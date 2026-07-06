// Learning-board API (plan §6.4) — thin wrappers around
// `jarvis.chat.learned_api.*`, the SM-gated + managed-only endpoints behind the
// Skills-page "Learning" tab. Mirrors src/api/skills.js: one `call` per
// endpoint; list/settings/batch args are JSON-encoded where the server
// `_parse_json`s them. `get_learning_status` is the only endpoint reachable on
// self-host (it reports `self_hosted` so the tab can show the managed-only
// empty state); every other call throws on a self-hosted bench.
import { call } from "frappe-ui"

const LR = "jarvis.chat.learned_api."

// ── list / board ─────────────────────────────────────────────────────────────
// Flat kwargs (NOT the frozen `filters` JSON envelope the four feature lists
// use): the endpoint takes domain/status/strength/search/surfaced directly.
// `surfaced`: 1 (default review board) | 0 | "all" (decided tabs).
export const listLearnedPatternsPage = (p = {}) =>
	call(LR + "list_learned_patterns_page", {
		domain: p.domain || "",
		status: p.status || "Proposed",
		strength: p.strength || "",
		search: p.search || "",
		surfaced: p.surfaced == null ? 1 : p.surfaced,
		start: p.start || 0,
		page_length: p.page_length || 20,
	})

// Full row + drill-down stats (raw n / confidence / wilson / gap), detected
// roles, compiled-bullet preview, exceptions (SM may see named parties), runs.
export const getLearnedPattern = (name) => call(LR + "get_learned_pattern", { name })

// ── lifecycle transitions (§6.5) — human SM actions, TOCTOU-safe server-side ──
// Proposed→Approved (or Stale→Approved). Passing an edited draft freezes the
// evidence line (draft_edited=1); omit it to approve as-drafted.
export const approveLearnedPattern = (name, editedSkillDraft) =>
	call(
		LR + "approve_learned_pattern",
		editedSkillDraft != null && editedSkillDraft !== ""
			? { name, edited_skill_draft: editedSkillDraft }
			: { name }
	)
export const unapproveLearnedPattern = (name) => call(LR + "unapprove_learned_pattern", { name })
export const rejectLearnedPattern = (name, reason) =>
	call(LR + "reject_learned_pattern", { name, reason })
// B/C insight-only disposition (Phase 1): records that the SM read the insight
// and dismisses it (stored server-side as a terminal Rejected + a stable note).
// A-class rows are refused server-side — they must be Approved to reach the
// container. Wired to the "Acknowledge (insight only)" card action.
export const acknowledgeLearnedPattern = (name) =>
	call(LR + "acknowledge_learned_pattern", { name })
export const restoreRejectedPattern = (name) => call(LR + "restore_rejected_pattern", { name })
export const snoozeLearnedPattern = (name, days) =>
	call(LR + "snooze_learned_pattern", { name, days })
// A-class only; a mixed batch (any B/C) is refused whole, server-side.
export const batchApprove = (names) =>
	call(LR + "batch_approve", { names: JSON.stringify(Array.from(names || [])) })

// ── apply / sync (learned skills ride the custom-skill push, §6.2) ───────────
export const applyLearnedSkills = () => call(LR + "apply_learned_skills")
// Proxies get_custom_skills_sync_status — same pill the Skills page polls.
export const getLearnedApplyStatus = () => call(LR + "get_learned_apply_status")
// Board badge: surfaced patterns still awaiting a decision.
export const pendingLearnedCount = () => call(LR + "pending_learned_count")

// ── run now (§5.1 / §5.2 manual bypass) ──────────────────────────────────────
export const runPatternAnalysisNow = () => call(LR + "run_pattern_analysis_now")

// ── settings + status (the in-tab config surface, §6.4) ──────────────────────
export const getLearningSettings = (includePreflight = 0) =>
	call(LR + "get_learning_settings", { include_preflight: includePreflight ? 1 : 0 })
export const setLearningSettings = (payload) =>
	call(LR + "set_learning_settings", { payload: JSON.stringify(payload || {}) })
// SM-only but NOT self-host-gated — the probe the tab uses to render the
// managed-only empty state (reports {self_hosted, enabled, last/next run, ...}).
export const getLearningStatus = () => call(LR + "get_learning_status")
