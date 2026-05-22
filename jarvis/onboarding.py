"""Onboarding — store the admin token + container connection into Jarvis
Settings, and thin server wrappers the onboarding page calls (so the browser
never holds admin creds). admin_client returns already-unwrapped admin data."""

import json

import frappe

from jarvis import admin_client


def write_connection(data: dict) -> None:
	"""Persist api_token / agent_url / agent_token into Jarvis Settings via
	db_set (no on_update creds-push retrigger during onboarding)."""
	if not isinstance(data, dict):
		return
	s = frappe.get_single("Jarvis Settings")
	if data.get("api_token"):
		s.db_set("jarvis_admin_api_key", data["api_token"])
	if data.get("agent_url"):
		s.db_set("agent_url", data["agent_url"])
	if data.get("agent_token"):
		s.db_set("agent_token", data["agent_token"])


@frappe.whitelist()
def sync_connection() -> dict:
	"""Pull the container connection from admin and store it. Daily scheduled +
	the page's 'Sync connection' button. No-op until onboarded/assigned."""
	settings = frappe.get_single("Jarvis Settings")
	if not (settings.get_password("jarvis_admin_api_key", raise_exception=False)):
		return {"synced": False, "reason": "not onboarded"}
	data = admin_client.get_connection()
	if data.get("agent_url"):
		write_connection(data)
		return {"synced": True, "tenant_status": data.get("tenant_status")}
	return {"synced": False, "tenant_status": data.get("tenant_status", "pending")}


@frappe.whitelist()
def list_plans() -> list:
	return admin_client.get_plans()


@frappe.whitelist()
def start_signup(email: str, company: str, plan: str) -> dict:
	"""Guest signup → store the api_token → return the Razorpay handles for Checkout."""
	data = admin_client.signup(email, company, plan)
	if data.get("api_token"):
		write_connection({"api_token": data["api_token"]})
	return data


@frappe.whitelist()
def finish_payment(payload) -> dict:
	"""Confirm Checkout success → store the returned container connection."""
	if isinstance(payload, str):
		payload = json.loads(payload)
	data = admin_client.confirm_payment(payload)
	write_connection(data)
	return data


@frappe.whitelist()
def renew() -> dict:
	"""Existing customer initiates a renewal payment; returns the Razorpay handles
	for Checkout. The page then completes Checkout and calls finish_payment."""
	return admin_client.renew()


@frappe.whitelist()
def dev_onboard(email: str, company: str, plan: str) -> dict:
	"""Local Razorpay-free onboarding: dev_force_signup → store token+connection."""
	data = admin_client.dev_signup(email, company, plan)
	write_connection(data)
	return data
