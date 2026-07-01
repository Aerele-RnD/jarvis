"""Best-effort pre-warming of the openclaw container's OpenAI prefix cache.

The first turn of a fresh session pays a cold provider prefill over the
large static system prefix (persona + skills + tool schema). That cache is
prefix-keyed and container-wide, so one cheap throwaway agent turn warms it
for every subsequent new chat in the same container. We never touch the
user's real session or write chat rows. Always best-effort; never raises.
"""
import uuid

import frappe

from jarvis import selfhost
from jarvis.chat.openclaw_client import OpenclawSession

# Cooldown between warm-ups for one bench. Comfortably inside gpt-5.5's
# prompt-cache retention window so the cache never cools between warms.
_WARM_COOLDOWN_S = 30 * 60


def _warm_cooldown_key() -> str:
	return f"jarvis:chat:prefix_warm:{frappe.local.site}"


def warm_prefix() -> bool:
	"""Fire one throwaway warm-up turn for this bench's container. Returns
	True if a warm-up was fired, False if skipped (debounced, not
	configured, self-hosted) or on any error. Never raises."""
	try:
		if selfhost.is_self_hosted():
			return False
		cache = frappe.cache()
		key = _warm_cooldown_key()
		if cache.get_value(key):
			return False
		settings = frappe.get_single("Jarvis Settings")
		gateway_url = (settings.agent_url or "").replace(
			"http://", "ws://").replace("https://", "wss://")
		gateway_token = settings.get_password("agent_token")
		if not gateway_url or not gateway_token:
			return False
		# Set the cooldown BEFORE the slow connect so a burst of opens (or a
		# broken gateway) cannot fan out into concurrent warm-ups.
		cache.set_value(key, "1", expires_in_sec=_WARM_COOLDOWN_S)
		sess = OpenclawSession.connect(gateway_url)
		try:
			throwaway = sess.create_session(label=f"jarvis-prewarm-{uuid.uuid4().hex[:8]}")
			sess.fire_agent(throwaway, "/think off warmup", uuid.uuid4().hex)
		finally:
			sess.close()
		return True
	except Exception:
		frappe.logger("jarvis.chat.prewarm").debug("prefix warm-up skipped", exc_info=True)
		return False
