"""SPA-facing CRUD + apply for customer-authored custom skills.

The SPA (``/jarvis`` Skills settings tab) calls these whitelisted methods to
manage ``Jarvis Custom Skill`` rows (owner-scoped) and to APPLY them to the
running container. Apply is explicit (a button), not on every save: each apply
restarts the container (the only way openclaw re-scans ``workspace/skills``),
so reconciling all skills in one push avoids a restart storm.

The apply path mirrors ``JarvisSettings.on_update`` / ``_enqueued_sync_via_admin``
(jarvis/jarvis/doctype/jarvis_settings/jarvis_settings.py): mark a pending status
synchronously, enqueue a deduped redis-locked worker that calls the admin app,
and flip the status to a terminal ``ok ...`` / ``failed: ...`` the SPA polls.
"""

import frappe
from frappe import _

from jarvis.chat.custom_skills import build_push_payload

SKILL = "Jarvis Custom Skill"
_SETTINGS = "Jarvis Settings"
_PUSH_JOB_ID = "jarvis_custom_skills_push"
_LOCK_NAME = "jarvis_custom_skills_push"


# --------------------------------------------------------------------------- #
# CRUD (owner-scoped; frappe.get_doc enforces if_owner on read/write/delete)
# --------------------------------------------------------------------------- #
SHARE = "Jarvis Custom Skill Share"


def _full_name(user: str) -> str:
	return frappe.db.get_value("User", user, "full_name") or user


def _skill_names_shared_with(user: str) -> list[str]:
	"""Skill row-names shared with ``user`` (child-table lookup, perm-free)."""
	return [
		r.parent
		for r in frappe.get_all(
			SHARE, filters={"user": user, "parenttype": SKILL}, fields=["parent"]
		)
	]


@frappe.whitelist()
def list_custom_skills() -> list[dict]:
	"""The current user's own skills PLUS skills shared with them (read-only).

	Own rows carry ``mine=1`` + ``shared_count``; shared-with-me rows carry
	``mine=0`` + ``shared_by`` (owner's name) and only when ``enabled`` (a draft
	the owner shared is not surfaced to recipients)."""
	me = frappe.session.user
	own = frappe.get_all(
		SKILL,
		filters={"owner": me},
		fields=["name", "skill_name", "description", "user_invocable", "enabled", "modified"],
		order_by="skill_name asc",
	)
	# One grouped query for ALL own rows' share counts (was an N+1 count per
	# skill — 123 queries at 121 skills, on every ChatView mount).
	share_counts: dict = {}
	own_names = [s["name"] for s in own]
	if own_names:
		for x in frappe.db.sql(
			"""SELECT parent, COUNT(*) n FROM `tabJarvis Custom Skill Share`
			WHERE parent IN %(names)s GROUP BY parent""",
			{"names": tuple(own_names)}, as_dict=True,
		):
			share_counts[x.parent] = x.n
	for s in own:
		s["mine"] = 1
		s["shared_count"] = share_counts.get(s["name"], 0)

	shared_names = _skill_names_shared_with(me)
	shared = []
	if shared_names:
		rows = frappe.get_all(
			SKILL,
			filters={"name": ["in", shared_names], "enabled": 1},
			fields=["name", "skill_name", "description", "user_invocable", "enabled", "owner", "modified"],
			order_by="skill_name asc",
		)
		# One query for the owners' display names (was a per-row lookup).
		full_names = {
			u.name: u.full_name
			for u in frappe.get_all(
				"User",
				filters={"name": ["in", list({r.owner for r in rows})]},
				fields=["name", "full_name"],
			)
		} if rows else {}
		for s in rows:
			s["mine"] = 0
			owner = s.pop("owner")
			s["shared_by"] = full_names.get(owner) or owner
			shared.append(s)
	return own + shared


# --------------------------------------------------------------------------- #
# Paginated list (frozen envelope) — chat-features-page-migration-design §2.2.
# ADDITIVE: list_custom_skills (above) STAYS for the composer "/" autocomplete.
# --------------------------------------------------------------------------- #
_SKILLS_SORTABLE = {"skill_name": "skill_name", "modified": "modified", "enabled": "enabled"}
_SKILLS_FILTERS = {"scope", "enabled", "user_invocable"}


def _lk(s: str) -> str:
	"""Escape LIKE wildcards in user search input (``\\`` is the default escape)."""
	return (s or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clamp_page(start, page_length) -> tuple[int, int]:
	try:
		start = max(0, int(start or 0))
	except (TypeError, ValueError):
		start = 0
	try:
		pl = int(page_length or 20)
	except (TypeError, ValueError):
		pl = 20
	return start, max(1, min(pl, 100))


def _bool01(v) -> int:
	try:
		iv = int(v)
	except (TypeError, ValueError):
		frappe.throw(_("Filter value must be 0 or 1."))
	if iv not in (0, 1):
		frappe.throw(_("Filter value must be 0 or 1."))
	return iv


def _load_filters(filters, allowed: set) -> dict:
	"""Parse ``filters`` (JSON string or dict), whitelist keys (unknown → throw),
	and drop empty values (an empty value = 'not filtering'; ``0`` is kept)."""
	if isinstance(filters, str):
		if filters.strip():
			try:
				raw = frappe.parse_json(filters)
			except Exception:
				raw = {}
		else:
			raw = {}
	else:
		raw = filters or {}
	if not isinstance(raw, dict):
		raw = {}
	out: dict = {}
	for k, v in raw.items():
		if k not in allowed:
			frappe.throw(_("Unknown filter: {0}").format(k))
		if v in (None, ""):
			continue
		out[k] = v
	return out


def _order_by(sort_field, sort_dir, sortable: dict, default_field, default_dir, prefix="") -> str:
	"""Build a safe ORDER BY: only whitelisted columns, direction normalized to
	asc/desc, a ``name`` tiebreak for stable OFFSET pagination. No user input is
	ever interpolated (columns come from ``sortable``; dir is a literal)."""
	col = sortable.get(sort_field or "")
	if not col:
		return f"{prefix}`{sortable[default_field]}` {default_dir}, {prefix}`name` asc"
	d = "desc" if (sort_dir or "").lower() == "desc" else "asc"
	return f"{prefix}`{col}` {d}, {prefix}`name` asc"


@frappe.whitelist()
def list_custom_skills_page(
	search: str = "",
	filters=None,
	sort_field: str = "",
	sort_dir: str = "",
	start: int = 0,
	page_length: int = 20,
) -> dict:
	"""Owner-scoped + shared-with-me skills, server-side search/filter/sort/paginate.

	Visibility parity with ``list_custom_skills``: own rows (any state) UNION
	shared-with-me rows (``enabled=1`` only) — expressed in ONE owner-scoped SQL
	WHERE so ``page_length``/``start`` slice the real result set (never a
	post-filtered page). Envelope: ``{rows, total, has_more, start, page_length}``.
	"""
	me = frappe.session.user
	start, pl = _clamp_page(start, page_length)
	f = _load_filters(filters, _SKILLS_FILTERS)
	shared = tuple(_skill_names_shared_with(me))

	conds: list[str] = []
	params: dict = {"me": me, "start": start, "page_length": pl}

	scope = f.get("scope")
	if scope is not None and scope not in ("mine", "shared"):
		frappe.throw(_("Invalid scope filter."))
	if scope == "mine":
		conds.append("owner = %(me)s")
	elif scope == "shared":
		if not shared:
			conds.append("1=0")
		else:
			params["shared"] = shared
			conds.append("(name IN %(shared)s AND enabled = 1)")
	else:  # both
		if shared:
			params["shared"] = shared
			conds.append("(owner = %(me)s OR (name IN %(shared)s AND enabled = 1))")
		else:
			conds.append("owner = %(me)s")

	if search:
		params["q"] = f"%{_lk(search)}%"
		conds.append("(skill_name LIKE %(q)s OR description LIKE %(q)s)")
	if "enabled" in f:
		params["enabled"] = _bool01(f["enabled"])
		conds.append("enabled = %(enabled)s")
	if "user_invocable" in f:
		params["user_invocable"] = _bool01(f["user_invocable"])
		conds.append("user_invocable = %(user_invocable)s")

	where = " AND ".join(conds)
	order = _order_by(sort_field, sort_dir, _SKILLS_SORTABLE, "skill_name", "asc")

	total = frappe.db.sql(
		f"SELECT COUNT(*) FROM `tabJarvis Custom Skill` WHERE {where}", params
	)[0][0]
	rows = frappe.db.sql(
		f"""SELECT name, skill_name, description, user_invocable, enabled, modified, owner
		FROM `tabJarvis Custom Skill`
		WHERE {where}
		ORDER BY {order}
		LIMIT %(page_length)s OFFSET %(start)s""",
		params, as_dict=True,
	)

	# One grouped child query for share counts over THIS page's own rows.
	my_names = [r.name for r in rows if r.owner == me]
	share_counts: dict = {}
	if my_names:
		for x in frappe.db.sql(
			"""SELECT parent, COUNT(*) n FROM `tabJarvis Custom Skill Share`
			WHERE parent IN %(names)s GROUP BY parent""",
			{"names": tuple(my_names)}, as_dict=True,
		):
			share_counts[x.parent] = x.n
	for r in rows:
		mine = 1 if r.owner == me else 0
		r["mine"] = mine
		r["shared_by"] = "" if mine else _full_name(r.owner)
		r["shared_count"] = share_counts.get(r.name, 0) if mine else 0
		r.pop("owner", None)

	return {
		"rows": rows,
		"total": total,
		"has_more": start + len(rows) < total,
		"start": start,
		"page_length": pl,
	}


@frappe.whitelist()
def get_custom_skill(name: str) -> dict:
	"""Return one skill incl. the full markdown instructions. Readable by the
	owner (editable) or a user it's shared with (read-only). ``can_edit`` tells
	the SPA which view to render."""
	doc = frappe.get_doc(SKILL, name)
	me = frappe.session.user
	is_owner = doc.owner == me
	if not is_owner and not frappe.db.exists(SHARE, {"parent": name, "user": me}):
		frappe.throw(_("You don't have access to this skill."), frappe.PermissionError)
	return {
		"name": doc.name,
		"skill_name": doc.skill_name,
		"description": doc.description,
		"instructions": doc.instructions,
		"user_invocable": int(doc.user_invocable or 0),
		"enabled": int(doc.enabled or 0),
		"modified": str(doc.modified or ""),
		"mine": int(is_owner),
		"can_edit": int(is_owner),
		"shared_by": "" if is_owner else _full_name(doc.owner),
	}


@frappe.whitelist()
def create_custom_skill(
	skill_name: str,
	description: str,
	instructions: str,
	user_invocable: int = 1,
	enabled: int = 1,
) -> dict:
	"""Create a skill. Validation (slug/caps) runs in the doctype's validate()."""
	doc = frappe.get_doc(
		{
			"doctype": SKILL,
			"skill_name": skill_name,
			"description": description,
			"instructions": instructions,
			"user_invocable": int(user_invocable or 0),
			"enabled": int(enabled or 0),
		}
	)
	doc.insert()
	frappe.db.commit()
	return {"ok": True, "data": {"name": doc.name, "skill_name": doc.skill_name}}


@frappe.whitelist()
def update_custom_skill(
	name: str,
	skill_name: str | None = None,
	description: str | None = None,
	instructions: str | None = None,
	user_invocable: int | None = None,
	enabled: int | None = None,
) -> dict:
	"""Update provided fields of a skill (owner-gated)."""
	doc = frappe.get_doc(SKILL, name)
	if skill_name is not None:
		doc.skill_name = skill_name
	if description is not None:
		doc.description = description
	if instructions is not None:
		doc.instructions = instructions
	if user_invocable is not None:
		doc.user_invocable = int(user_invocable)
	if enabled is not None:
		doc.enabled = int(enabled)
	doc.save()
	frappe.db.commit()
	return {"ok": True, "data": {"name": doc.name, "modified": str(doc.modified)}}


@frappe.whitelist()
def delete_custom_skill(name: str) -> dict:
	"""Delete a skill row (owner-gated). The delete only propagates to the
	container on the next Apply (the fleet endpoint does a full reconcile)."""
	frappe.delete_doc(SKILL, name)  # honors if_owner permission
	frappe.db.commit()
	return {"ok": True}


@frappe.whitelist()
def delete_custom_skills_bulk(names: str | list | None = None) -> dict:
	"""Bulk delete skills the caller OWNS (DESIGN-V3 §8.3 / D20). ``names`` is a
	JSON array of skill row-names. Per-row try/except so one bad row never
	aborts the batch: shared-with-me / foreign rows skip with ``not owner``.
	One deduped skills-apply enqueue at the end (mirrors the save/delete
	auto-apply) — only when something was actually deleted.
	Returns ``{deleted, skipped: [{name, reason}]}``."""
	raw = frappe.parse_json(names) if isinstance(names, str) else (names or [])
	items = [str(n) for n in raw if n] if isinstance(raw, list) else []
	me = frappe.session.user
	deleted = 0
	skipped: list[dict] = []
	for n in items:
		try:
			doc = frappe.get_doc(SKILL, n)
			if doc.owner != me:
				skipped.append({"name": n, "reason": "not owner"})
				continue
			frappe.delete_doc(SKILL, n)  # same path as delete_custom_skill (if_owner)
			deleted += 1
		except frappe.DoesNotExistError:
			skipped.append({"name": n, "reason": "not found"})
		except frappe.PermissionError:
			skipped.append({"name": n, "reason": "not permitted"})
		except Exception:
			# Never leak internal exception text to the client — log server-side.
			frappe.log_error(
				title="Jarvis: bulk skill delete failed", message=frappe.get_traceback()
			)
			skipped.append({"name": n, "reason": "error"})
	frappe.db.commit()
	if deleted:
		apply_custom_skills()
	return {"deleted": deleted, "skipped": skipped}


# --------------------------------------------------------------------------- #
# Sharing (owner shares a skill with specific users; recipients get read-only
# use — they cannot edit, disable, delete, or re-share it)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def list_shareable_users() -> list[dict]:
	"""Users the current user can share a skill with (staff on this bench,
	excluding self + Guest). Feeds the share multiselect."""
	me = frappe.session.user
	return frappe.get_all(
		"User",
		filters={"enabled": 1, "name": ["not in", [me, "Guest", "Administrator"]]},
		fields=["name", "full_name"],
		order_by="full_name asc",
		limit_page_length=500,
	)


@frappe.whitelist()
def get_skill_shares(name: str) -> dict:
	"""Return who a skill is currently shared with (owner only)."""
	doc = frappe.get_doc(SKILL, name)
	if doc.owner != frappe.session.user:
		frappe.throw(_("Only the owner can manage sharing."), frappe.PermissionError)
	return {
		"users": [
			{"name": r.user, "full_name": _full_name(r.user)} for r in (doc.shared_with or [])
		]
	}


@frappe.whitelist()
def share_custom_skill(name: str, users=None) -> dict:
	"""Replace a skill's share list with ``users`` (a JSON array or list of user
	ids). Owner only. Recipients get read-only use; they can never re-share."""
	doc = frappe.get_doc(SKILL, name)
	doc.check_permission("write")  # owner-gate
	if doc.owner != frappe.session.user:
		frappe.throw(_("Only the owner can share this skill."), frappe.PermissionError)
	raw = frappe.parse_json(users) if isinstance(users, str) else (users or [])
	clean, seen = [], set()
	for u in raw if isinstance(raw, list) else []:
		u = (u or "").strip()
		if not u or u in seen or u == doc.owner or u == "Guest":
			continue
		if not frappe.db.exists("User", u):
			continue
		seen.add(u)
		clean.append(u)
	doc.set("shared_with", [{"user": u} for u in clean])
	doc.save()
	frappe.db.commit()
	return {"ok": True, "data": {"count": len(clean)}}


# --------------------------------------------------------------------------- #
# Apply (explicit push to the container, via admin → fleet)
# --------------------------------------------------------------------------- #
@frappe.whitelist()
def get_custom_skills_sync_status() -> dict:
	"""Lightweight poller mirroring onboarding.get_llm_sync_status."""
	s = frappe.get_single(_SETTINGS)
	status = s.get("custom_skills_sync_status") or ""
	return {
		"last_sync_at": str(s.get("custom_skills_synced_at") or ""),
		"last_sync_status": status,
		"pending": status.startswith("pending:"),
	}


@frappe.whitelist()
def apply_custom_skills() -> dict:
	"""Push all enabled skills to the assistant (one restart). Explicit action.

	Builds the payload synchronously so size/cap errors surface immediately,
	marks a pending status, then enqueues the deduped worker (mirrors
	``JarvisSettings.on_update``).
	"""
	skills = build_push_payload()
	frappe.db.set_single_value(
		_SETTINGS, "custom_skills_sync_status", "pending: applying skills"
	)
	frappe.db.commit()
	run_inline = bool(frappe.flags.in_test or frappe.flags.run_admin_sync_inline)
	frappe.enqueue(
		"jarvis.chat.custom_skills_api._enqueued_push_custom_skills",
		queue="long",
		timeout=180,
		enqueue_after_commit=not run_inline,
		now=run_inline,
		job_id=_PUSH_JOB_ID,
		deduplicate=True,
	)
	return {"ok": True, "custom_skills_sync_status": "pending: applying skills", "count": len(skills)}


def _enqueued_push_custom_skills() -> None:
	"""Background worker: push the enabled skills via admin → fleet → container.

	Re-builds the payload fresh (never trust a payload passed across the queue
	boundary) and mirrors ``_sync_via_admin``'s try/except/finally so the status
	never stays at ``pending:`` forever.
	"""
	from jarvis import admin_client
	from jarvis._redis_lock import redis_lock

	with redis_lock(_LOCK_NAME, timeout_s=180, blocking_timeout_s=60.0) as acquired:
		if not acquired:
			frappe.db.set_single_value(
				_SETTINGS, "custom_skills_sync_status", "failed: skipped (concurrent sync)"
			)
			frappe.db.commit()
			return

		terminal_written = False
		try:
			payload = build_push_payload()
			admin_client.post_push_custom_skills(skills=payload)
			frappe.db.set_value(
				_SETTINGS,
				_SETTINGS,
				{
					"custom_skills_synced_at": frappe.utils.now(),
					"custom_skills_sync_status": f"ok (applied {len(payload)} via admin)",
				},
			)
			terminal_written = True
		except admin_client.AdminAuthError as e:
			_fail(f"failed: auth: {e}")
			terminal_written = True
			frappe.log_error(title="Jarvis: custom-skills admin auth failed", message=frappe.get_traceback())
		except admin_client.AdminUnreachableError as e:
			_fail(f"failed: admin unreachable: {e}")
			terminal_written = True
			frappe.log_error(title="Jarvis: custom-skills admin unreachable", message=frappe.get_traceback())
		except admin_client.AdminRateLimitedError as e:
			retry = getattr(e, "retry_after_seconds", 0) or 0
			retry_str = f"retry_after={retry}s" if retry > 0 else "retry shortly"
			_fail(f"failed: rate-limited; {retry_str}")
			terminal_written = True
		except admin_client.AdminValidationError as e:
			_fail(f"failed: invalid: {e}")
			terminal_written = True
		finally:
			if not terminal_written:
				try:
					_fail("failed: unexpected error; see Error Log")
				except Exception:
					pass
		frappe.db.commit()


def _fail(status: str) -> None:
	frappe.db.set_value(
		_SETTINGS,
		_SETTINGS,
		{"custom_skills_synced_at": frappe.utils.now(), "custom_skills_sync_status": status},
	)
