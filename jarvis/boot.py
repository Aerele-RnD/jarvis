"""Frappe boot_session hook.

Frappe builds the per-session ``bootinfo`` blob that the desk + page JS
reads from ``frappe.boot`` at page load. Apps register a single hook
function via ``hooks.boot_session`` to write their own keys onto that
blob. This file is that function for jarvis.

Keys we set:

- ``jarvis_onboarded`` - whether the customer has finished the Jarvis
  setup wizard, used by the desk's not-onboarded banner
  (``jarvis_onboarding_banner.bundle.js``) to decide whether to nag a
  System Manager toward ``/jarvis/onboarding``.
- ``jarvis_has_access`` - whether the current user may reach Jarvis at
  all (``jarvis.permissions.has_jarvis_access``). Lets the desk's
  floating Jarvis button send an unauthorized user to
  ``/jarvis-no-access`` instead of opening the chat panel.
"""

import frappe


def set_jarvis_boot(bootinfo):
	"""Run once per session at page load. Adds jarvis-specific keys to the
	bootinfo blob so JS can branch on them without an extra round trip."""
	# Drives the desk's not-onboarded banner (jarvis_onboarding_banner.bundle.js).
	# Uses is_ready_for_chat rather than the lighter is_onboarded because the
	# SPA wizard now covers both signup AND the LLM-connect step (Phase 2
	# Task 5) - is_onboarded only reflects step 1 (admin api_key present) and
	# would mark a signed-up-but-not-connected customer as "done", silencing
	# the nag before setup is actually finished.
	try:
		from jarvis.account import is_ready_for_chat

		bootinfo.jarvis_onboarded = bool((is_ready_for_chat() or {}).get("ready"))
	except Exception:
		bootinfo.jarvis_onboarded = True  # fail-safe: never nag on a boot error

	# Drives the desk's floating Jarvis button: an unauthorized user is routed
	# to /jarvis-no-access instead of the chat panel opening. Import kept
	# inside the try block (like the blocks above) so tests can patch
	# jarvis.permissions.has_jarvis_access without touching module load order.
	try:
		from jarvis.permissions import has_jarvis_access

		bootinfo.jarvis_has_access = bool(has_jarvis_access())
	except Exception:
		bootinfo.jarvis_has_access = False  # fail-closed; the no-access page self-heals
