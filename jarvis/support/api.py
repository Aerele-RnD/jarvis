"""Bench-side support endpoints (Plan 3 B3).

Role-gated: the caller's scope (own|all) is derived here from their bench roles and forwarded to
the control-plane proxy along with their identity. The control plane re-derives the customer from
the API key, so a role-less caller can't reach another customer's data. Admin-side errors are
surfaced as clean toasts via _surface. House envelope: {"ok": True, "data": ...}.
"""

import frappe

from jarvis import admin_client
from jarvis.onboarding import _surface
from jarvis.permissions import support_scope


def _scope() -> str:
	scope = support_scope()
	if scope is None:
		frappe.throw("You don't have Jarvis support access.", frappe.PermissionError)
	return scope


@frappe.whitelist()
def list_tickets() -> dict:
	scope = _scope()
	return {
		"ok": True,
		"data": _surface(admin_client.support_list_tickets, requesting_user=frappe.session.user, scope=scope),
	}


@frappe.whitelist()
def create_ticket(subject: str, body: str = "") -> dict:
	scope = _scope()
	return {
		"ok": True,
		"data": _surface(
			admin_client.support_create_ticket,
			subject=subject,
			body=body or "",
			requesting_user=frappe.session.user,
			scope=scope,
		),
	}


@frappe.whitelist()
def get_thread(ticket: str) -> dict:
	scope = _scope()
	return {
		"ok": True,
		"data": _surface(
			admin_client.support_get_thread,
			ticket=ticket,
			requesting_user=frappe.session.user,
			scope=scope,
		),
	}


@frappe.whitelist()
def reply(ticket: str, body: str) -> dict:
	scope = _scope()
	return {
		"ok": True,
		"data": _surface(
			admin_client.support_reply,
			ticket=ticket,
			body=body,
			requesting_user=frappe.session.user,
			scope=scope,
		),
	}


@frappe.whitelist()
def close_ticket(ticket: str) -> dict:
	scope = _scope()
	return {
		"ok": True,
		"data": _surface(
			admin_client.support_close_ticket,
			ticket=ticket,
			requesting_user=frappe.session.user,
			scope=scope,
		),
	}


@frappe.whitelist()
def awaiting_count() -> dict:
	scope = _scope()
	return {
		"ok": True,
		"data": _surface(
			admin_client.support_awaiting_count, requesting_user=frappe.session.user, scope=scope
		),
	}
