"""Domain-skill compilation + materialization (plan sections 6.2, 6.3).

Approved/Active learned patterns are consolidated into at most six Administrator-
owned ``Jarvis Custom Skill`` rows - ``learned-selling/buying/stock/accounts/
projects/org`` (wire ``custom-learned-<domain>``) - pushed through the EXISTING
custom-skill chain. No new push path; the 25-skill bench cap is enforced by an
apply-time pre-check only (``build_push_payload`` truncation is untouched - plan
section 6.2).

PHASE-1 BODY RULE (owner decision, portal-chat finding): only ``effective_
sensitivity == "A"`` (org-level) patterns compile into the PUSHED body. Any
party-named bullet (effective B/C) is insight-only in Phase 1 and never reaches
the shared container. A domain with no A-class survivors compiles to nothing and
its managed row is deleted on apply.

Body template is deterministic (plan section 6.3): ASCII, ``->`` not arrows, no
statistical jargon, the File Box / OCR carve-out, the Interplay clause, JLP refs
for traceability, and "K known exceptions (see board)" (A-class never names an
exception party). Every interpolated value passes the sanitizer.

ACTIVATION TIMING TRADEOFF (plan section 6.2): confirming a container push
before flipping Approved -> Active needs poll/callback wiring the Phase-1 apply
does not have, so patterns flip to Active at ENQUEUE time (right after the
deduped push job is queued). A failed push therefore leaves Active patterns
whose text has not yet reached the container; the next apply re-pushes and the
custom-skills sync status surfaces the failure. Accepted for Phase 1.
"""

from __future__ import annotations

import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import now_datetime, today

from jarvis.learning.sanitizer import (
	safe_value,
	sanitize_value,
	scan_instruction_injection,
)

JLP = "Jarvis Learned Pattern"
JLP_ROLE = "Jarvis Learned Pattern Role"
SKILL = "Jarvis Custom Skill"
SKILL_ALLOWED_ROLE = "Jarvis Custom Skill Allowed Role"

MANAGED_OWNER = "Administrator"
DOMAINS = ("selling", "buying", "stock", "accounts", "projects", "org")

# Compiled-content caps (plan section 6.3).
MAX_BODY = 18000
MAX_DESC = 500
MAX_BULLET = 400
# Mirrors chat.custom_skills.MAX_SKILLS_PER_PUSH; the apply pre-check gate.
BENCH_SKILL_CAP = 25
# Rough per-bullet overhead (section headers, newline) reserved during budgeting.
_BULLET_MARGIN = 60

# Apply single-flight + un-approve TOCTOU guard (plan section 6.2). The redis
# lock serializes concurrent Applies; the cache marker is what
# ``learned_api.unapprove_learned_pattern`` reads to refuse an un-approve while a
# compile -> flip is in flight (a status re-read alone loses the race).
_APPLY_LOCK = "jarvis_learned_apply"
_APPLY_LOCK_TTL = 600
_APPLY_MARKER = "jarvis:learned_apply_in_progress"

_BAND_RANK = {"High": 0, "Medium": 1, "Low": 2}

_DOMAIN_NOUN = {
	"selling": "selling",
	"buying": "buying",
	"stock": "stock",
	"accounts": "accounts",
	"projects": "projects",
	"org": "org-wide",
}

# When an A-class pattern's antecedent is org-level (no entity name to front-
# load), the description borrows a short topic label from the template instead.
_TOPIC_BY_TEMPLATE = {
	"quotation-validity": "quotation validity",
	"tc-letterhead": "terms and letterhead",
	"pi-update-stock": "update-stock on purchase invoices",
	"default-vs-usage": "default vs actual usage",
	"naming-series": "naming series",
	"selective-item-pricing": "customer-specific pricing",
	"group-payment-terms": "group payment terms",
	"mode-of-payment": "modes of payment",
	"itemgroup-warehouse": "item-group warehouses",
	"stock-entry-route": "stock-entry routes",
	"billing-method": "project billing methods",
}

# Control chars to strip inside a bullet line (whitespace handled via split()).
_LINE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# ASCII-fold a few common unicode punctuation glyphs so bodies stay ASCII.
_UNICODE_FOLD = {
	"→": "->", "←": "<-", "—": "-", "–": "-",
	"‘": "'", "’": "'", "“": '"', "”": '"',
	"…": "...", " ": " ",
}


def _domain_skill_name(domain: str) -> str:
	return f"learned-{domain}"


# --------------------------------------------------------------------------- #
# compile (read-only; safe for preview)
# --------------------------------------------------------------------------- #
def compile_domain_skills() -> dict:
	"""Group Approved/Active A-class patterns by domain and render one skill spec
	per non-empty domain. Read-only: no writes, no flips (that is apply's job).

	Returns ``{domain: {skill_name, description, body, allowed_roles,
	pattern_names, deferred}}`` for domains with at least one compiled bullet.
	"""
	rows = frappe.get_all(
		JLP,
		filters={"status": ["in", ["Approved", "Active"]], "effective_sensitivity": "A"},
		fields=[
			"name", "domain", "company", "pattern_statement", "skill_draft",
			"strength_band", "support_n", "detector_id", "evidence",
			"draft_edited", "last_seen_run",
		],
	)
	if not rows:
		return {}

	roles_map = _roles_by_pattern([r["name"] for r in rows])

	by_domain: dict[str, list] = defaultdict(list)
	for r in rows:
		by_domain[r["domain"]].append(r)

	result: dict[str, dict] = {}
	for domain, patterns in by_domain.items():
		patterns.sort(key=_strength_key)
		run_label = _run_label(patterns)
		included, deferred = _select_within_budget(domain, patterns, run_label)
		if not included:
			# A single bullet exceeded the whole budget (degenerate); skip domain.
			continue
		allowed: set[str] = set()
		for p in included:
			allowed |= roles_map.get(p["name"], set())
		result[domain] = {
			"skill_name": _domain_skill_name(domain),
			"description": _description(domain, included),
			"body": _render_body(domain, included, run_label),
			"allowed_roles": sorted(allowed),
			"pattern_names": [p["name"] for p in included],
			"deferred": [p["name"] for p in deferred],
		}
	return result


def compile_preview(domain: str) -> str:
	"""The rendered body a domain WOULD compile to right now (UI preview). Empty
	string when the domain has no A-class Approved/Active patterns."""
	return (compile_domain_skills().get(domain) or {}).get("body", "")


def preview_bullet(pattern_name: str) -> str:
	"""The single compiled bullet THIS pattern would render into (the drill-down
	"compiled rule preview" - plan section 6.4). Read-only, sensitivity-agnostic:
	B/C rows are insight-only and never reach the pushed body, but the board still
	previews the bullet the SM is deciding on. Empty string when the row is gone."""
	row = frappe.db.get_value(
		JLP, pattern_name,
		["name", "domain", "skill_draft", "pattern_statement"],
		as_dict=True,
	)
	if not row:
		return ""
	return _bullet(row)


# --------------------------------------------------------------------------- #
# apply (writes: upsert managed rows, flip statuses, enqueue the existing push)
# --------------------------------------------------------------------------- #
def apply_learned_skills() -> dict:
	"""Recompile every domain, upsert the <=6 Administrator-owned managed rows
	(deleting emptied domains), flip compiled Approved patterns to Active, then
	reuse the deduped ``jarvis_custom_skills_push`` job. Cap + slug pre-checks run
	first and abort with actionable errors (``build_push_payload`` unchanged).

	Single-flight: a redis lock serializes concurrent Applies and an
	apply-in-progress marker is set BEFORE compile so ``unapprove_learned_pattern``
	refuses during the compile -> flip window (plan section 6.2 TOCTOU)."""
	from jarvis._redis_lock import redis_lock

	with redis_lock(_APPLY_LOCK, timeout_s=_APPLY_LOCK_TTL, blocking_timeout_s=0) as acquired:
		if not acquired:
			frappe.throw(
				_(
					"Another Apply is already in progress; wait for it to finish, then apply again."
				)
			)
		_set_apply_marker(True)
		try:
			return _apply_learned_skills_locked()
		finally:
			_set_apply_marker(False)


def _apply_learned_skills_locked() -> dict:
	compiled = compile_domain_skills()
	_precheck_bench_cap(compiled)
	_precheck_slug_ownership()

	original_user = frappe.session.user
	prev_engine = frappe.flags.jarvis_pattern_engine
	applied_domains: list[str] = []
	deleted_domains: list[str] = []
	skill_by_domain: dict[str, str] = {}
	activated = 0
	try:
		# Own the managed rows as Administrator (normal users cannot reach them)
		# and lift the JLP transition guard for the Approved -> Active flips.
		frappe.set_user(MANAGED_OWNER)
		frappe.flags.jarvis_pattern_engine = True

		existing_managed = {
			r["skill_name"]: r["name"]
			for r in frappe.get_all(
				SKILL, filters={"managed_by_learning": 1}, fields=["name", "skill_name"]
			)
		}
		for domain, spec in compiled.items():
			skill_by_domain[domain] = _upsert_managed_skill(spec)
			applied_domains.append(domain)

		# Delete managed rows whose domain no longer has any compiled patterns.
		for sname, row_name in existing_managed.items():
			domain = sname[len("learned-"):] if sname.startswith("learned-") else sname
			if domain not in compiled:
				frappe.delete_doc(SKILL, row_name, ignore_permissions=True, force=True)
				deleted_domains.append(domain)

		activated = _finalize_patterns(compiled, skill_by_domain)
		frappe.db.commit()
	finally:
		frappe.flags.jarvis_pattern_engine = prev_engine
		frappe.set_user(original_user)

	# Reuse the existing deduped push (do NOT touch build_push_payload).
	from jarvis.chat.custom_skills_api import apply_custom_skills

	sync = apply_custom_skills()
	return {
		"applied_domains": sorted(applied_domains),
		"deleted_domains": sorted(d for d in deleted_domains if d),
		"activated": activated,
		"skills": skill_by_domain,
		"sync": sync,
	}


def _set_apply_marker(on: bool) -> None:
	"""Flip the apply-in-progress cache marker (best-effort; the redis-lock TTL is
	the backstop if a crash skips the clear)."""
	try:
		cache = frappe.cache()
		if on:
			cache.set_value(_APPLY_MARKER, "1", expires_in_sec=_APPLY_LOCK_TTL)
		else:
			cache.delete_value(_APPLY_MARKER)
	except Exception:
		pass


def apply_in_progress() -> bool:
	"""True while an Apply is between compile and its post-flip commit - the
	un-approve TOCTOU window. ``learned_api.unapprove_learned_pattern`` reads it."""
	try:
		return bool(frappe.cache().get_value(_APPLY_MARKER))
	except Exception:
		return False


def _precheck_slug_ownership() -> None:
	"""Abort before any write if a NON-Administrator custom skill already claims a
	``learned-`` slug (the reserved managed-skill prefix). ``_upsert_managed_skill``
	keys only on ``{managed_by_learning:1, skill_name}``, so a squatting customer
	row would otherwise collide in the shared push. Belt-and-suspenders with the
	prefix reservation (plan section 6.2)."""
	rows = frappe.get_all(
		SKILL,
		filters={"skill_name": ["like", "learned-%"], "owner": ["!=", MANAGED_OWNER]},
		fields=["skill_name", "owner"],
	)
	if rows:
		offenders = ", ".join(f"'{r.skill_name}' (owner {r.owner})" for r in rows)
		frappe.throw(
			_(
				"Cannot apply learned skills: the reserved 'learned-' skill-name prefix is "
				"already used by non-managed custom skill(s): {0}. Rename or delete them, then "
				"apply again."
			).format(offenders)
		)


def _precheck_bench_cap(compiled: dict) -> None:
	"""Abort before any write if the resulting bench-wide enabled count would
	exceed the 25 cap (plan section 6.2: pre-check only). Counts enabled
	NON-managed skills + the learned domain rows we are about to (re)enable."""
	existing = frappe.db.count(SKILL, {"enabled": 1, "managed_by_learning": 0})
	learned_rows = len(compiled)
	if existing + learned_rows > BENCH_SKILL_CAP:
		frappe.throw(
			_(
				"Cannot apply learned skills: {0} enabled custom skill(s) plus {1} learned "
				"domain skill(s) would exceed the {2}-skill limit for this assistant. Disable "
				"or delete some custom skills, then apply again."
			).format(existing, learned_rows, BENCH_SKILL_CAP)
		)


def _upsert_managed_skill(spec: dict) -> str:
	"""Create or update one managed ``learned-<domain>`` row. Owner = the current
	session user (Administrator during apply). Returns the row name."""
	sname = spec["skill_name"]
	existing = frappe.db.get_value(
		SKILL, {"managed_by_learning": 1, "skill_name": sname}, "name"
	)
	if existing:
		doc = frappe.get_doc(SKILL, existing)
	else:
		doc = frappe.new_doc(SKILL)
		doc.skill_name = sname

	doc.description = spec["description"]
	doc.instructions = spec["body"]
	doc.user_invocable = 0
	doc.enabled = 1
	doc.managed_by_learning = 1
	doc.set("allowed_roles", [{"role": r} for r in spec["allowed_roles"]])
	doc.save(ignore_permissions=True) if existing else doc.insert(ignore_permissions=True)
	return doc.name


def _finalize_patterns(compiled: dict, skill_by_domain: dict) -> int:
	"""Flip compiled Approved patterns to Active + stamp materialized_skill;
	re-stamp already-Active ones; mark deferred patterns compile_deferred. Runs
	with the engine flag set so the Approved -> Active transition is allowed."""
	activated = 0
	now = now_datetime()
	for domain, spec in compiled.items():
		skill_row = skill_by_domain.get(domain)
		for name in spec["pattern_names"]:
			status = frappe.db.get_value(JLP, name, "status")
			if status == "Approved":
				doc = frappe.get_doc(JLP, name)
				doc.status = "Active"
				doc.materialized_skill = skill_row
				doc.last_validated_at = now
				doc.save(ignore_permissions=True)
				activated += 1
			elif status == "Active":  # refresh the materialized-skill pointer only
				frappe.db.set_value(
					JLP, name,
					{"materialized_skill": skill_row, "last_validated_at": now},
					update_modified=False,
				)
			# else: the row is no longer Approved/Active (e.g. un-approved to
			# Proposed inside the apply window) - skip it. Never stamp
			# materialized_skill on a row that is not live in the pushed body.
		for name in spec["deferred"]:
			_mark_compile_deferred(name)
	return activated


def _mark_compile_deferred(name: str) -> None:
	ev = frappe.db.get_value(JLP, name, "evidence")
	try:
		data = frappe.parse_json(ev) if ev else {}
	except Exception:
		data = {}
	if not isinstance(data, dict):
		data = {}
	data["compile_deferred"] = True
	frappe.db.set_value(
		JLP, name, {"evidence": frappe.as_json(data)}, update_modified=False
	)


# --------------------------------------------------------------------------- #
# body / description rendering
# --------------------------------------------------------------------------- #
def _render_body(domain: str, patterns: list, run_label: str) -> str:
	noun = _DOMAIN_NOUN.get(domain, domain)
	lines = [
		f"# Learned {noun} habits",
		"",
		f"Scope: defaults mined from this site's history. Last analyzed: {run_label}.",
		"These are learned defaults, not hard rules: apply them silently when they fit; when the",
		"user's request conflicts or you must deviate, say so and confirm with the user.",
		"",
		"## How to use these rules",
		"- Each rule is a default with its evidence and known exceptions.",
		'- Known exceptions are legitimate deviations: do not "correct" them.',
		"- Explicit user instructions always beat a learned default.",
		"- In File Box / OCR / unattended flows: NEVER ask or confirm. Printed document values and",
		"  the ocr-data-entry skill's rules win over any learned default. Escalate doubts to the",
		"  approval board, per the OCR contract.",
		"",
	]

	companies = sorted({(p.get("company") or "") for p in patterns if p.get("company")})
	multi_company = len(companies) > 1

	if not multi_company:
		lines.append("## All roles")
		for p in patterns:
			lines.append(_bullet(p))
	else:
		org_level = [p for p in patterns if not p.get("company")]
		if org_level:
			lines.append("## All roles")
			for p in org_level:
				lines.append(_bullet(p))
			lines.append("")
		for company in companies:
			# safe_value (not sanitize_value): an injection-shaped mined company
			# name is swapped for a neutral placeholder, matching antecedent handling.
			lines.append(f"### Company: {safe_value(company)}")
			for p in patterns:
				if (p.get("company") or "") == company:
					lines.append(_bullet(p))
			lines.append("")

	lines.append("")
	lines.append("## Interplay")
	lines.extend(_interplay_lines(domain))
	return "\n".join(lines).strip() + "\n"


def _interplay_lines(domain: str) -> list[str]:
	if domain == "org":
		lead = "- Persona skills give generic guidance; where this file states a learned default, the"
	else:
		lead = f"- Persona skills (erpnext-{domain}) give generic guidance; where this file states a"
	return [
		lead,
		"  learned default wins - EXCEPT in OCR/File Box flows (above).",
		"- If another custom skill conflicts, follow the custom skill and note the conflict.",
	]


def _bullet(row: dict) -> str:
	"""One compiled bullet: sanitized draft + JLP ref. Injection-shaped drafts
	are withheld with a board pointer rather than embedded (plan section 6.3)."""
	name = row["name"]
	draft = (row.get("skill_draft") or "").strip()
	if not draft:
		draft = "- " + (row.get("pattern_statement") or "").strip()

	if scan_instruction_injection(draft):
		return (
			f"- A learned {row.get('domain') or ''} default ({name}) was withheld because its "
			f"data did not pass the safety scan; review it on the board. ({name})"
		)

	line = _sanitize_bullet_line(draft)
	if not line.startswith("- "):
		line = "- " + line.lstrip("-").strip()
	if name not in line:
		line = f"{line} ({name})"
	if len(line) > MAX_BULLET:
		ref = f" ({name})"
		line = line[: MAX_BULLET - len(ref)].rstrip() + ref
	return line


def _fold_ascii_line(text: str) -> str:
	"""Collapse text to one safe ASCII line: strip control chars, fold known
	unicode punctuation, neutralize stray backticks (so a mined value cannot open
	a dangling code span), collapse whitespace. Entity names (already quoted in
	the draft) are preserved; only structural safety is enforced here."""
	t = _LINE_CONTROL_RE.sub("", text or "")
	for bad, good in _UNICODE_FOLD.items():
		t = t.replace(bad, good)
	t = t.replace("`", "'")
	return " ".join(t.split()).strip()


def _sanitize_bullet_line(text: str) -> str:
	"""One safe ASCII bullet line (shares the fold with the description pass)."""
	return _fold_ascii_line(text)


def _description(domain: str, patterns: list) -> str:
	"""Front-load concrete entity names + doctypes, then the retrieval hint
	(plan section 6.3). Capped at 500 chars; every subject is sanitized."""
	subjects: list[str] = []
	seen: set[str] = set()
	for p in patterns:
		subj = _subject(p)
		if subj and subj.lower() not in seen:
			seen.add(subj.lower())
			subjects.append(subj)
		if len(subjects) >= 6:
			break

	doctypes = _doctypes(patterns)
	noun = _DOMAIN_NOUN.get(domain, domain)
	head = f"Learned {noun} habits for this org"
	if subjects:
		head += ": " + ", ".join(subjects)
	if doctypes:
		head += " - on " + ", ".join(doctypes)
	desc = f"{head}. Use whenever creating, editing or answering questions about {noun} documents."
	# Final structural pass: the whole pushed description is folded to a safe ASCII
	# line (control chars stripped, unicode punctuation folded, backticks
	# neutralized) - the body gets this per bullet; the description did not.
	desc = _fold_ascii_line(desc)
	if len(desc) > MAX_DESC:
		desc = desc[: MAX_DESC - 1].rstrip().rstrip(",") + "."
	return desc[:MAX_DESC]


def _subject(row: dict) -> str:
	spec = _spec(row.get("detector_id"))
	ev = _parse_evidence(row.get("evidence"))
	antecedent = ev.get("antecedent")
	kind = (spec or {}).get("antecedent_kind")
	if antecedent not in (None, "", "org") and kind != "org":
		# safe_value (not sanitize_value): an injection-shaped mined antecedent is
		# swapped for the placeholder, so the DESCRIPTION field is injection-safe
		# just like the body values (plan section 6.3 / 7 T4).
		return safe_value(antecedent)
	topic = _TOPIC_BY_TEMPLATE.get((spec or {}).get("skill_template"))
	return topic or ""


def _doctypes(patterns: list) -> list[str]:
	out: list[str] = []
	seen: set[str] = set()
	for p in patterns:
		spec = _spec(p.get("detector_id"))
		dt = (spec or {}).get("doctype")
		# "DocType" is the internal antecedent for naming-series; not user-facing.
		if dt and dt != "DocType" and dt not in seen:
			seen.add(dt)
			out.append(dt)
		if len(out) >= 4:
			break
	return out


# --------------------------------------------------------------------------- #
# budgeting + helpers
# --------------------------------------------------------------------------- #
def _select_within_budget(domain: str, patterns: list, run_label: str) -> tuple[list, list]:
	"""Greedily include patterns (strongest first) while the rendered body stays
	<= 18k; the rest are deferred (plan section 6.2)."""
	skeleton_len = len(_render_body(domain, [], run_label))
	running = skeleton_len
	included: list = []
	deferred: list = []
	for p in patterns:
		cost = len(_bullet(p)) + 1
		if running + cost + _BULLET_MARGIN <= MAX_BODY:
			included.append(p)
			running += cost
		else:
			deferred.append(p)

	# Safety: if section overhead still tipped us over, shed the weakest included.
	while included and len(_render_body(domain, included, run_label)) > MAX_BODY:
		deferred.append(included.pop())
	return included, deferred


def _strength_key(p: dict) -> tuple:
	return (_BAND_RANK.get(p.get("strength_band"), 3), -(p.get("support_n") or 0), p.get("name"))


def _run_label(patterns: list) -> str:
	runs = sorted(p.get("last_seen_run") for p in patterns if p.get("last_seen_run"))
	run = runs[-1] if runs else None
	date_str = today()
	return f"{date_str} (run {run})" if run else date_str


def _roles_by_pattern(names: list[str]) -> dict:
	roles_map: dict = defaultdict(set)
	if not names:
		return roles_map
	for rr in frappe.get_all(
		JLP_ROLE, filters={"parent": ["in", names], "parenttype": JLP}, fields=["parent", "role"]
	):
		if rr.get("role"):
			roles_map[rr["parent"]].add(rr["role"])
	return roles_map


def _parse_evidence(ev) -> dict:
	if not ev:
		return {}
	if isinstance(ev, dict):
		return ev
	try:
		parsed = frappe.parse_json(ev)
	except Exception:
		return {}
	return parsed if isinstance(parsed, dict) else {}


def _spec(detector_id):
	if not detector_id:
		return None
	try:
		from jarvis.learning import registry

		return registry.get_detector(detector_id)
	except Exception:
		return None
