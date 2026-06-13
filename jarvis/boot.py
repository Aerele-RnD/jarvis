"""Frappe boot_session hook.

Frappe builds the per-session ``bootinfo`` blob that the desk + page JS
reads from ``frappe.boot`` at page load. Apps register a single hook
function via ``hooks.boot_session`` to write their own keys onto that
blob. This file is that function for jarvis.

Today the only key we set is ``jarvis_sandbox_mode``, replacing the
previous JS-side check on ``frappe.boot.developer_mode``. Sandbox mode
controls whether the developer-onboarding shortcut + the Jarvis Settings
DEV-only reset button are surfaced; see ``jarvis.dev.is_sandbox_mode``
for the resolution rules.
"""

import frappe


def set_jarvis_boot(bootinfo):
	"""Run once per session at page load. Adds jarvis-specific keys to the
	bootinfo blob so JS can branch on them without an extra round trip."""
	from jarvis.dev import is_sandbox_mode
	try:
		bootinfo.jarvis_sandbox_mode = bool(is_sandbox_mode())
	except Exception:
		# Don't let a misconfigured doctype or missing migration break the
		# session boot. JS treats the missing key as false (default off).
		bootinfo.jarvis_sandbox_mode = False
