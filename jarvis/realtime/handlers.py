"""Frappe realtime handlers for jarvis.

Frappe's Python realtime process (frappe/realtime/server.py) discovers and
imports ``<app>/realtime/handlers.py`` from every installed app at startup
via ``discover_app_handlers()``. The realtime process is the **only** Frappe
process that imports this module; gunicorn / RQ workers / the scheduler
never reach this code.

What this module does on import:

- If the bench has ``socketio_backend: "python"`` set in
  ``common_site_config.json``, spawn a long-lived gevent greenlet that
  subscribes to ``jarvis:chat:send:<site>`` on Redis pub/sub and dispatches
  each message to ``jarvis.chat.turn_handler.handle_chat_send`` in its own
  greenlet (so many concurrent turns share the one realtime process). The
  outer greenlet wraps the subscribe loop in a watchdog: any uncaught
  exception inside the loop is logged and the loop is respawned after a
  short backoff so a single bad turn does not silently disable chat for
  the whole bench.

- If the bench is on the default Node socketio backend (or any value other
  than ``"python"``), this module is still imported but the subscriber is
  **never spawned**. The Path B code path is dormant. Chat continues to go
  through ``jarvis.chat.api.send_message -> frappe.enqueue ->
  jarvis.chat.worker.run_agent_turn`` exactly as before. There is no
  feature-flag toggle inside jarvis to flip; the ``socketio_backend``
  config value is the single source of truth.

The matching publisher lives at ``jarvis.chat.dispatch.publish_chat_send``;
both sides use ``_channel(site)`` (private to dispatch.py) to keep the
channel name in one place.
"""
from __future__ import annotations

import json
import time

import frappe

_SUBSCRIBER_SPAWNED = False

# How long the watchdog sleeps before restarting the subscribe loop after an
# unhandled exception. Short enough that chat recovers on the next turn, long
# enough that a hard-failure tight loop does not spam logs.
_WATCHDOG_BACKOFF_S = 5

# Site-scoped channel format. Must match jarvis.chat.dispatch._channel.
_CHANNEL_TEMPLATE = "jarvis:chat:send:{site}"


def _python_backend_active() -> bool:
	"""True iff the bench has opted into the Python socketio backend.

	The realtime process is one-per-bench, so reading ``frappe.conf`` here
	(populated from common_site_config.json) is the correct check; per-site
	overrides do not apply at this layer.
	"""
	return (frappe.conf.get("socketio_backend") or "").strip().lower() == "python"


def _site_name() -> str:
	"""Best-effort current site name for channel scoping.

	``frappe.local.site`` is the canonical answer once a request context is
	open; at realtime startup we may be outside any site context, in which
	case ``frappe.conf.get('default_site')`` is the closest equivalent.
	Returning an empty string from here would publish/subscribe on
	``jarvis:chat:send:`` (no site), which is wrong; raise instead so a
	misconfigured bench fails loudly at boot.
	"""
	site = getattr(frappe.local, "site", None) or frappe.conf.get("default_site") or ""
	if not site:
		raise RuntimeError(
			"jarvis.realtime.handlers: cannot determine site name for chat "
			"subscriber channel; set default_site in common_site_config.json "
			"or run under a site context"
		)
	return site


def _run_one(raw: bytes | str) -> None:
	"""Decode one pub/sub message and dispatch it to the shared turn
	handler. Exceptions are logged and swallowed so one bad payload does
	not take down the subscribe loop (a swallowed-here exception also
	swallows itself out of the watchdog's reach, which is intentional;
	the watchdog only kicks in on subscribe-side failures)."""
	# Late import to avoid pulling the heavy chat-turn module into every
	# realtime-process startup when the Python backend is not active.
	from jarvis.chat.turn_handler import handle_chat_send

	try:
		body = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
		payload = json.loads(body)
		if not isinstance(payload, dict):
			raise ValueError(f"expected dict payload, got {type(payload).__name__}")
		handle_chat_send(payload)
	except Exception:
		frappe.log_error(
			title="jarvis chat subscriber: handler failed",
			message=frappe.get_traceback(),
		)


def _subscribe_loop_once() -> None:
	"""Open one Redis pub/sub subscription and dispatch every message
	until the connection drops. The watchdog wrapping this function is
	responsible for restarting it; this function itself never retries."""
	import gevent

	channel = _CHANNEL_TEMPLATE.format(site=_site_name())
	conn = frappe.cache().get_redis_connection()
	pubsub = conn.pubsub()
	pubsub.subscribe(channel)
	frappe.logger().info(f"jarvis chat subscriber: listening on {channel}")
	for message in pubsub.listen():
		if message.get("type") != "message":
			continue
		gevent.spawn(_run_one, message.get("data"))


def _watchdog_loop() -> None:
	"""Forever-loop wrapper: run the subscribe loop, and on any unhandled
	exception log it and restart after a short backoff. The realtime
	process supervisor will only restart THIS file's import, not the
	module-level subscribe greenlet, so a crashed loop without this
	watchdog would silently disable chat until the next bench restart."""
	while True:
		try:
			_subscribe_loop_once()
		except Exception:
			frappe.log_error(
				title="jarvis chat subscriber: subscribe loop crashed",
				message=frappe.get_traceback(),
			)
		# Backoff before reconnect. Use time.sleep (gevent monkey-patches it)
		# rather than gevent.sleep so this module stays import-time safe
		# under both backends; the realtime process has monkey.patch_all()
		# called before discover_app_handlers, so time.sleep yields the hub.
		time.sleep(_WATCHDOG_BACKOFF_S)


def maybe_start_chat_subscriber() -> bool:
	"""Spawn the chat-send subscriber if the Python socketio backend is
	active. Idempotent (a second call is a no-op). Returns True iff a new
	greenlet was spawned by this call (mostly useful for tests; production
	code calls it for the side effect)."""
	global _SUBSCRIBER_SPAWNED
	if _SUBSCRIBER_SPAWNED:
		return False
	if not _python_backend_active():
		return False
	import gevent

	gevent.spawn(_watchdog_loop)
	_SUBSCRIBER_SPAWNED = True
	frappe.logger().info(
		"jarvis chat subscriber: watchdog greenlet spawned "
		"(socketio_backend=python)"
	)
	return True


# Fire on module import. Frappe's realtime process imports this module via
# discover_app_handlers() during boot, after gevent.monkey.patch_all() has
# already run, so spawning a greenlet here is safe.
maybe_start_chat_subscriber()
