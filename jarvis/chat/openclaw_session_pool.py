"""WebSocket connection pool for OpenclawSession.

Each chat worker turn previously opened a fresh WS to the tenant's
openclaw gateway: DNS + TCP + TLS + WS upgrade + 3-phase signed
handshake before sending the agent RPC. The spike (workflow
``w0s0vqhqu``) measured this as 50-200ms per turn (recurring) and
confirmed:

- The gateway dispatches concurrent RPCs on one WS (multiplex)
- One warm WS per gateway can serve every subsequent turn

CAVEAT (2026-07 latency review): the RQ worker *parent* process is
long-lived, but stock ``bench worker`` uses rq's forking Worker — each
job runs in a forked work-horse child that exits after the job, taking
this module-level pool with it. The pool therefore only amortizes under
a non-forking executor: the Python-socketio realtime process (Path B,
``socketio_backend: "python"``) or ``bench worker-pool`` with
``FRAPPE_BACKGROUND_WORKERS_NOFORK=1``. The pool-hit/pool-miss log
lines in ``checkout``/``_do_connect`` measure which world you're in.

This module maintains one pooled OpenclawSession per gateway URL,
per worker process, with lazy reconnect on stale / idle / error.

Concurrency: single-process RQ workers are single-threaded, so the
per-entry lock is uncontended in practice. The lock exists for
safety against threaded / no-fork RQ variants and to prevent races
inside a process that might somehow spawn a second concurrent
checkout against the same URL.

Lifetime: an ``atexit`` hook drains all pooled sessions when the
worker process exits. SIGTERM during a job lets the in-flight call
finish before the drain proceeds (atexit runs after the foreground
work completes).

The bench-side ``OpenclawSession`` is NOT safe for concurrent
``stream_agent_turn`` calls on the same WS — ``_recv`` is shared
state and would steal frames between turns. So the pool gives an
exclusive checkout: one turn per pooled session at a time. The
amortization win is over SEQUENTIAL turns within a worker process,
not concurrent multiplexing. Multi-worker concurrency arrives via
multiple worker processes each maintaining their own pool entry.
"""
from __future__ import annotations

import atexit
import contextlib
import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

from jarvis.chat.openclaw_client import OpenclawSession
from jarvis.exceptions import OpenclawUnreachableError


logger = logging.getLogger(__name__)


# Max idle seconds before a pooled session is discarded on next
# checkout. Below the typical 5-min openclaw gateway idle disconnect
# so the WS is fresh when handed out. Aggressive eviction is cheap;
# the next checkout reconnects.
IDLE_MAX_S = 240


@dataclass
class _PooledEntry:
	"""One pooled session per gateway URL.

	Each entry has its own lock so checkouts to different URLs don't
	contend. Within a process, a single entry is exclusive per turn
	because the worker is single-threaded and the bench-side client
	isn't safe for concurrent ``stream_agent_turn`` calls on the same
	WS.
	"""
	session: OpenclawSession
	lock: threading.Lock
	last_used: float
	gateway_url: str


# Module-level pool keyed by gateway_url. Mutations to the pool dict
# (creating / deleting entries) go through ``_POOL_LOCK``; per-entry
# concurrent-use protection is on the entry's own lock.
_POOL: dict[str, _PooledEntry] = {}
_POOL_LOCK = threading.Lock()


@contextlib.contextmanager
def checkout(gateway_url: str) -> Iterator[OpenclawSession]:
	"""Acquire a healthy OpenclawSession for ``gateway_url``.

	Reuses a pooled session if one exists and passes the healthcheck;
	otherwise opens a fresh connection (paying the handshake cost
	once). The yielded session is exclusive to this caller until the
	context exits. On exception inside the block, the session is
	discarded from the pool (next checkout reconnects).
	"""
	entry = _get_or_create_entry(gateway_url)
	entry.lock.acquire()
	evicted = False
	try:
		# Healthcheck: discard if connection went away or sat idle
		# too long. Either reason → reconnect now.
		if not _is_alive(entry.session, entry.last_used):
			logger.info(
				"openclaw_session_pool: stale entry, reconnecting "
				"gateway=%s idle_s=%.1f connected=%s",
				gateway_url,
				time.monotonic() - entry.last_used,
				_safe_connected(entry.session),
			)
			_close_quietly(entry.session)
			entry.session = _do_connect(gateway_url)
		else:
			# Symmetric to the pool-miss log in _do_connect so the hit rate
			# is measurable from logs (latency plan, Phase 0). Under stock
			# fork-per-job RQ this line should ~never appear — that absence
			# is itself the signal that Phase 2 (persistent relay) is needed.
			logger.info(
				"openclaw_session_pool: pool-hit gateway=%s idle_s=%.1f",
				gateway_url, time.monotonic() - entry.last_used,
			)
		yield entry.session
		entry.last_used = time.monotonic()
	except OpenclawUnreachableError:
		# Connection failed mid-use. Evict so the next checkout opens
		# a fresh WS rather than handing out the broken one.
		_evict(gateway_url, entry)
		evicted = True
		raise
	finally:
		if not evicted:
			entry.lock.release()
		else:
			# _evict left the lock held so we release uniformly here.
			try:
				entry.lock.release()
			except RuntimeError:
				pass


def _get_or_create_entry(gateway_url: str) -> _PooledEntry:
	"""Look up the entry for ``gateway_url`` or create one with a
	fresh connection. The pool-dict mutation is locked; the connection
	open happens outside the pool lock to avoid blocking other URLs."""
	with _POOL_LOCK:
		entry = _POOL.get(gateway_url)
		if entry is not None:
			return entry
	# Slow path: open a connection. Done outside ``_POOL_LOCK`` so a
	# slow connect doesn't block other gateways. Race: if two callers
	# hit this at once, both will create sessions; the second
	# insertion under ``_POOL_LOCK`` wins and we close the loser.
	# Cheap, rare (single-threaded workers).
	sess = _do_connect(gateway_url)
	new_entry = _PooledEntry(
		session=sess,
		lock=threading.Lock(),
		last_used=time.monotonic(),
		gateway_url=gateway_url,
	)
	with _POOL_LOCK:
		existing = _POOL.get(gateway_url)
		if existing is not None:
			_close_quietly(sess)
			return existing
		_POOL[gateway_url] = new_entry
	return new_entry


def _do_connect(gateway_url: str) -> OpenclawSession:
	"""Open a fresh WS + handshake. Wraps ``OpenclawSession.connect``
	for timing visibility — the actual connect logic stays in the
	client. Phase-level breakdown is logged inside ``_attempt_connect``
	itself; this just captures the total."""
	t0 = time.monotonic()
	sess = OpenclawSession.connect(gateway_url)
	elapsed_ms = int((time.monotonic() - t0) * 1000)
	logger.info(
		"openclaw_session_pool: pool-miss connect gateway=%s total_ms=%d",
		gateway_url, elapsed_ms,
	)
	return sess


def _is_alive(session: OpenclawSession, last_used: float) -> bool:
	"""True if the session looks healthy enough to reuse: WS is open
	and the entry hasn't sat idle past the eviction threshold."""
	if time.monotonic() - last_used > IDLE_MAX_S:
		return False
	return _safe_connected(session)


def _safe_connected(session: OpenclawSession) -> bool:
	"""Defensively read ``session._ws.connected``; some WS libraries
	don't expose the field, in which case treat as not-connected."""
	try:
		return bool(session._ws.connected)
	except AttributeError:
		return False


def _close_quietly(session: OpenclawSession) -> None:
	"""Close a session, swallowing any errors. Used during eviction
	where the session is already dead / dying."""
	try:
		session.close()
	except Exception:
		pass


def _evict(gateway_url: str, entry: _PooledEntry) -> None:
	"""Remove the entry from the pool and close its session. The
	caller holds ``entry.lock``; we leave it locked so the ``finally``
	clause in ``checkout`` releases uniformly."""
	with _POOL_LOCK:
		if _POOL.get(gateway_url) is entry:
			_POOL.pop(gateway_url, None)
	_close_quietly(entry.session)


def drain_all() -> None:
	"""Close every pooled session. Called from ``atexit`` on worker
	shutdown so the gateway sees clean disconnects rather than dangling
	half-open TCP connections. Also exposed for tests."""
	with _POOL_LOCK:
		entries = list(_POOL.values())
		_POOL.clear()
	for entry in entries:
		_close_quietly(entry.session)


# Register the drain hook at module import time. ``atexit`` runs in
# reverse-registration order, which is correct: any code that
# registered before us (e.g. Frappe DB connections) drains first,
# then we close the WS.
atexit.register(drain_all)
