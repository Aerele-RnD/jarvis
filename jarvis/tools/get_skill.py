"""Fetch one saved skill's full instructions (Jarvis Custom Skill row).

Accepts the bare authored slug (``invoicing``), the container wire slug
(``custom-invoicing``) or a learned-namespace slug (``learned-selling`` —
stored verbatim as the row's skill_name). ``skill_name`` is unique per OWNER,
not globally, so several rows may match; the caller's own row wins.
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.find_skills import _require_system_user, _visible

SKILL = "Jarvis Custom Skill"
_CUSTOM_PREFIX = "custom-"


def get_skill(skill_name: str) -> dict:
    """Return one skill the calling user may use: ``{skill_name, description,
    instructions, scope, enabled, user_invocable}``."""
    user = _require_system_user()
    raw = (skill_name or "").strip().lower()
    if not raw:
        raise InvalidArgumentError("skill_name is required")

    candidates = {raw}
    if raw.startswith(_CUSTOM_PREFIX):
        # The wire slug is custom-<bare>; rows store the bare slug (a stored
        # skill_name can never itself start with the reserved prefix).
        candidates.add(raw[len(_CUSTOM_PREFIX):])

    rows = frappe.get_all(
        SKILL,
        filters={"skill_name": ["in", sorted(candidates)]},
        fields=[
            "name", "owner", "skill_name", "description", "instructions",
            "scope", "enabled", "user_invocable",
        ],
    )
    if not rows:
        raise InvalidArgumentError(f"unknown skill: {skill_name}")

    user_roles = frappe.get_roles(user)
    usable = [r for r in rows if _visible(r, user, user_roles)]
    if not usable:
        raise PermissionDeniedError(f"no access to skill: {skill_name}")

    row = next((r for r in usable if r.owner == user), usable[0])
    return {
        "skill_name": row.skill_name,
        "description": row.description or "",
        "instructions": row.instructions or "",
        "scope": row.scope or "Org",
        "enabled": int(row.enabled or 0),
        "user_invocable": int(row.user_invocable or 0),
    }
