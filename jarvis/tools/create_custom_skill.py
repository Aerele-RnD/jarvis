"""Save a new skill (Jarvis Custom Skill row) from chat.

The agent captures a procedure the user just walked it through and saves it
as a skill owned by the session user. Defaults to scope=Personal (private,
never pushed to the shared container catalog); scope=Org rows join the
shared catalog only after an admin clicks Apply. This tool NEVER triggers a
push/apply itself — Apply restarts the container and stays a deliberate
human action.

Confirmation-gated in jarvis/api.py (_GATED_WRITES): the model path parks
the call behind a human confirm card.
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools.find_skills import _require_system_user

SKILL = "Jarvis Custom Skill"
_SCOPES = ("Org", "Personal")


def create_custom_skill(
    skill_name: str,
    description: str,
    instructions: str,
    scope: str = "Personal",
    user_invocable: int = 1,
) -> dict:
    """Insert a skill row as the session user; the DocType controller enforces
    the slug grammar, length caps, per-owner uniqueness/cap and the reserved
    ``custom-``/``learned-`` prefixes. Returns ``{name, skill_name, scope,
    note}``."""
    _require_system_user()

    scope = (scope or "Personal").strip().capitalize()
    if scope not in _SCOPES:
        raise InvalidArgumentError("scope must be 'Org' or 'Personal'")

    ui = user_invocable
    if isinstance(ui, str):
        ui = ui.strip().lower() in ("1", "true", "yes", "on")

    doc = frappe.get_doc(
        {
            "doctype": SKILL,
            "skill_name": skill_name,
            "description": description,
            "instructions": instructions,
            "scope": scope,
            "user_invocable": 1 if ui else 0,
            "enabled": 1,
        }
    )
    try:
        doc.insert()
    except (frappe.ValidationError, frappe.DuplicateEntryError) as e:
        # Controller frappe.throw()s carry clean user-facing messages; re-raise
        # as the tool-envelope type so direct callers and the dispatch wrapper
        # classify them identically.
        raise InvalidArgumentError(str(e) or type(e).__name__)

    if scope == "Org":
        note = (
            "Saved. Org-scope skills reach the assistant's skill catalog only "
            "after an admin clicks Apply on the Skills page; until then recall "
            "it with jarvis__find_skills / jarvis__get_skill."
        )
    else:
        note = (
            "Saved as a personal skill: private to its owner and never pushed "
            "to the shared catalog; recall it with jarvis__find_skills / "
            "jarvis__get_skill."
        )
    return {
        "name": doc.name,
        "skill_name": doc.skill_name,
        "scope": doc.scope or "Org",
        "note": note,
    }
