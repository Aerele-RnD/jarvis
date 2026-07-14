"""One policy: the test suite does not talk to the network.

Why this module exists
----------------------
Running the jarvis test suite against a bench that has a real tenant DESTROYS it. On
2026-07-14, ``bench --site site.jarvis run-tests --app jarvis`` wiped a live tenant's LLM
pool and an OAuth subscription credential that could not be recovered.

The mechanism: ``Jarvis Settings.on_update`` runs the admin sync INLINE under
``frappe.flags.in_test`` -- deliberately, "so tests see the final status without polling"
(``_enqueue_pool_sync``). Test helpers call ``settings.save()`` + ``frappe.db.commit()``,
and the commit defeats ``FrappeTestCase``'s rollback, so the FIXTURE pool persists in the
real Jarvis Settings and gets pushed to a live fleet-agent -- which rewrites the tenant's
bifrost config, tears down cliproxy via ``--remove-orphans``, and deletes the OAuth token
blob. Frappe keeps no ``Version`` history for a Single, so there is no undo.

CI never caught it because **CI is safe by ACCIDENT**: nothing answers there, so the call
fails and the test sees an error status. On a developer's bench, jarvis.admin and the
fleet-agent ARE running -- so the identical call SUCCEEDS.

Why it lives in one module
--------------------------
Because a guard with holes gives false confidence. The app has SIX ways onto the network,
and only one of them is the catastrophic one -- but the others are not harmless either:

  * admin_client        -> rewrites the tenant's pool, deletes OAuth blobs  (catastrophic)
  * chat/openclaw_client-> mutates live session state, burns LLM quota
  * oauth/api           -> exchanges/refreshes REAL provider tokens
  * chat/voice          -> burns real STT quota
  * selfhost            -> probes a real customer LLM endpoint
  * chat/link_fetch     -> fetches arbitrary URLs from the open internet

One policy, one place to reason about, no holes.

The contract
------------
``blocked_reason()`` DECIDES; the caller RAISES. That split is deliberate: every call site
raises its own natural "unreachable" error (AdminUnreachableError, OpenclawUnreachableError
...), which is the SAME exception each already raises when the far end is down. A local run
therefore behaves exactly as CI already does, and every existing caller's error handling
applies unchanged. A brand-new exception type would have quietly changed test outcomes.
"""
from __future__ import annotations

import frappe

# Per-surface opt-in flags, for the rare test that genuinely means to reach the network.
# Nothing in the ordinary suite sets any of them.
ALLOW_ADMIN = "allow_real_admin_calls"
ALLOW_OPENCLAW = "allow_real_openclaw_calls"
ALLOW_OUTBOUND = "allow_real_outbound_calls"  # oauth / voice / selfhost / link-fetch


def blocked_reason(url: str, allow_flag: str = ALLOW_OUTBOUND) -> str | None:
	"""The message to raise with, or None when the call may proceed.

	Returns None outside a test run, so production is untouched: ``frappe.flags.in_test``
	is set by the test runner and by nothing else.
	"""
	if not frappe.flags.get("in_test"):
		return None
	if frappe.flags.get(allow_flag):
		return None
	return (
		f"BLOCKED: a test tried to reach the network ({url!r}). The test suite must not "
		"talk to a real admin, fleet-agent, openclaw container, or upstream provider -- "
		"on a developer's bench those are RUNNING, and a test that reaches them has "
		"pushed its fixtures into a live tenant (this really happened: it destroyed an "
		"OAuth credential with no undo). Mock the transport in your test, or set "
		f"frappe.flags.{allow_flag} = True if you truly mean to call out."
	)
