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
@frappe.whitelist()
def list_custom_skills() -> list[dict]:
	"""Return the current user's custom skills (no instructions body)."""
	return frappe.get_all(
		SKILL,
		filters={"owner": frappe.session.user},
		fields=["name", "skill_name", "description", "user_invocable", "enabled", "modified"],
		order_by="skill_name asc",
	)


@frappe.whitelist()
def get_custom_skill(name: str) -> dict:
	"""Return one skill incl. the full markdown instructions (owner-gated)."""
	doc = frappe.get_doc(SKILL, name)
	return {
		"name": doc.name,
		"skill_name": doc.skill_name,
		"description": doc.description,
		"instructions": doc.instructions,
		"user_invocable": int(doc.user_invocable or 0),
		"enabled": int(doc.enabled or 0),
		"modified": str(doc.modified or ""),
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
