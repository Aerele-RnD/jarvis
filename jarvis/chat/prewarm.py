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

# Cooldown between warm-ups for one bench. Set below the */30 cron
# interval so keep_warm re-warms on each tick instead of every other.
# Comfortably inside gpt-5.5's prompt-cache retention window so the
# cache never cools between warms.
_WARM_COOLDOWN_S = 25 * 60

# Short in-progress TTL set BEFORE the slow connect so concurrent opens
# cannot fan out into concurrent warm-ups. Expires quickly on failure
# so a failed warm retries soon rather than blocking for the full cooldown.
# Accepted best-effort SET race: two concurrent callers may both pass
# get_value before either sets this key; the second warm is harmless
# (#6 accepted best-effort).
_WARM_INPROGRESS_S = 90


def _warm_cooldown_key() -> str:
	return f"jarvis:chat:prefix_warm:{frappe.local.site}"


def _gateway_ws_url(settings) -> str:
	"""Convert Jarvis Settings.agent_url http(s):// -> ws(s)://."""
	return (settings.agent_url or "").replace(
		"http://", "ws://").replace("https://", "wss://")


def _resolve_default_model_and_provider(settings) -> tuple[str, str | None]:
	"""Return (model, provider) a real default new-chat first turn would use.

	Mirrors turn_handler._resolve_model_and_provider for the no-override
	case: default model = Jarvis Settings.llm_model; provider id only in
	oauth mode. Reuses turn_handler's provider map as the single source of
	truth so the warm-up cannot drift to a different provider's cache."""
	from jarvis.chat.turn_handler import _PROVIDER_LABEL_TO_OPENCLAW_ID
	model = settings.llm_model or ""
	provider = (
		_PROVIDER_LABEL_TO_OPENCLAW_ID.get(settings.llm_provider)
		if settings.llm_auth_mode == "oauth"
		else None
	)
	return model, provider


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
		# OpenclawSession.connect authenticates via device pairing
		# (ensure_paired / chat_device_* creds), NOT agent_token.
		# agent_token is empty on managed/device-paired benches.
		gateway_url = _gateway_ws_url(settings)
		if not gateway_url:
			return False
		# Set a short in-progress marker BEFORE the slow connect so a burst
		# of opens (or a broken gateway) cannot fan out into concurrent
		# warm-ups. On any exception this short marker expires in
		# _WARM_INPROGRESS_S, allowing a retry soon. The full cooldown is
		# only set after a successful warm so a transient blip does not
		# disable warming for 25 min.
		cache.set_value(key, "1", expires_in_sec=_WARM_INPROGRESS_S)
		model, provider = _resolve_default_model_and_provider(settings)
		sess = OpenclawSession.connect(gateway_url)
		try:
			throwaway = sess.create_session(label=f"jarvis-prewarm-{uuid.uuid4().hex[:8]}")
			sess.fire_agent(
				throwaway, "/think off warmup", uuid.uuid4().hex,
				model=model or None, provider=provider,
			)
		finally:
			sess.close()
		# Warm succeeded: arm the full cooldown so the next cron tick skips.
		cache.set_value(key, "1", expires_in_sec=_WARM_COOLDOWN_S)
		return True
	except Exception:
		frappe.logger("jarvis.chat.prewarm").warning("prefix warm-up failed", exc_info=True)
		return False


def keep_warm_if_active() -> None:
	"""Scheduler entry: keep the prefix cache warm for benches with recent
	chat activity, so a returning user's first turn is warm after an idle
	gap. No-op on idle or self-hosted benches. Runs on the existing
	scheduler; the per-bench debounce in warm_prefix bounds frequency."""
	try:
		if selfhost.is_self_hosted():
			return
		cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-30)
		recent = frappe.db.exists("Jarvis Chat Message", {"creation": [">", cutoff]})
		if not recent:
			return
		warm_prefix()
	except Exception:
		frappe.logger("jarvis.chat.prewarm").debug("keep_warm skipped", exc_info=True)


def enqueue_warm_if_due() -> None:
	"""Warm-on-chat-load: enqueue a prefix warm-up in a background job if the
	per-bench cooldown has lapsed. Called from list_conversations (which every
	chat surface hits on load), so the first turn of a new chat gets a warm
	prefix without a frontend change. Just a cheap cache read on the request
	path - the connect + warm runs off the web worker. Best-effort, never
	raises, and debounced so repeated calls do not fan out into jobs."""
	try:
		if selfhost.is_self_hosted():
			return
		if frappe.cache().get_value(_warm_cooldown_key()):
			return
		frappe.enqueue("jarvis.chat.prewarm.warm_prefix", queue="short")
	except Exception:
		frappe.logger("jarvis.chat.prewarm").debug("enqueue_warm_if_due skipped", exc_info=True)
