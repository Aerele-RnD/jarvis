"""Per-company sales / billing / payment totals for a Customer or
Supplier - the same scalar bag that powers the dashboard cards on the
Customer / Supplier form in Desk.

Wraps ``erpnext.accounts.party.get_dashboard_info``. Useful for
"give me a quick read on Acme" questions where the agent would
otherwise have to assemble totals from five different reports.

Tool exposed as ``get_party_dashboard_info`` (more descriptive than the
underlying ``get_dashboard_info``) so the agent doesn't confuse this
with any future per-doc dashboard helper.
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import (
    InvalidArgumentError,
    PermissionDeniedError,
)

_VALID_PARTY_TYPES = ("Customer", "Supplier")


def get_party_dashboard_info(
    party_type: str,
    party: str,
    loyalty_program: str | None = None,
) -> dict:
    """Return ``{dashboard, party_type, party}`` where ``dashboard`` is
    the raw per-company list ERPNext renders on the form (each entry
    has billing_this_year, total_unpaid, currency, etc.).
    """
    if party_type not in _VALID_PARTY_TYPES:
        raise InvalidArgumentError(
            f"party_type must be one of {list(_VALID_PARTY_TYPES)}",
        )
    if not party:
        raise InvalidArgumentError("party is required")
    if not frappe.db.exists(party_type, party):
        raise InvalidArgumentError(f"unknown {party_type}: {party}")
    if not frappe.has_permission(party_type, "read", doc=party):
        raise PermissionDeniedError(f"no read permission on {party_type} {party}")

    from erpnext.accounts.party import get_dashboard_info as _gdi

    dashboard = _gdi(
        party_type=party_type, party=party, loyalty_program=loyalty_program,
    )
    return {
        "dashboard": dashboard,
        "party_type": party_type,
        "party": party,
    }
