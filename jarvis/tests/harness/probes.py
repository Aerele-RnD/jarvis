"""Metric probes for the six production criteria (C1–C6).

Two kinds:

  * Trace extractors — pure functions over TurnResult lists + the TraceRecorder:
      first_token (from submit AND from send), queue_wait, flush-gap series
      (C3, DB-commit cadence + publish cadence), dispatch->first-event dwell
      (C4), and the p50/p95/p99 summarizer.

  * Live probes — real work against the running bench:
      CanaryProbe  — enqueues short+long RQ canaries every 10s to the REAL
                     workers and times their wait, plus a real Desk HTTP GET
                     (C6). background_flood() generates real RQ occupancy so
                     the canary is measured under load, not just idle.
      measure_stop_visible — stop-click -> visible aborted terminal (SUX-12).

Percentiles use linear interpolation (numpy-free). All wall-clock probes are
repeated; the caller states N in the report.
"""

from __future__ import annotations

import itertools
import threading
import time
import urllib.request
import uuid

# --------------------------------------------------------------------------- #
# percentile + summary
# --------------------------------------------------------------------------- #


def percentile(values, p: float):
	xs = sorted(v for v in values if v is not None)
	if not xs:
		return None
	if len(xs) == 1:
		return xs[0]
	k = (len(xs) - 1) * (p / 100.0)
	lo = int(k)
	hi = min(lo + 1, len(xs) - 1)
	frac = k - lo
	return xs[lo] + (xs[hi] - xs[lo]) * frac


def summarize(values) -> dict:
	xs = [v for v in values if v is not None]
	if not xs:
		return {"n": 0, "min": None, "p50": None, "p95": None, "p99": None, "max": None, "mean": None}
	return {
		"n": len(xs),
		"min": round(min(xs), 2),
		"p50": round(percentile(xs, 50), 2),
		"p95": round(percentile(xs, 95), 2),
		"p99": round(percentile(xs, 99), 2),
		"max": round(max(xs), 2),
		"mean": round(sum(xs) / len(xs), 2),
	}


# --------------------------------------------------------------------------- #
# trace extractors
# --------------------------------------------------------------------------- #


def first_token_from_submit(results) -> list:
	return [r.first_token_from_submit_ms() for r in results]


def first_token_from_send(results) -> list:
	return [r.first_token_from_send_ms() for r in results]


def queue_wait(results) -> list:
	return [r.queue_wait_ms() for r in results]


def total(results) -> list:
	return [r.total_ms() for r in results]


def _gap_series(recorder, run_id, source, kind) -> list:
	evs = [e for e in recorder.events_for(run_id) if e.source == source and (kind is None or e.kind == kind)]
	gaps = []
	for a, b in itertools.pairwise(evs):
		gaps.append((b.t_mono - a.t_mono) * 1000.0)
	return gaps


def flush_gap_series(recorder, run_id) -> list:
	"""C3: inter-DB-commit gap between successive assistant content flushes
	(the coalesced batcher cadence, _ASSISTANT_BATCH_INTERVAL_MS=250)."""
	return _gap_series(recorder, run_id, "db", "msg.content.flush")


def publish_gap_series(recorder, run_id) -> list:
	"""Companion to C3: inter-publish gap (assistant:delta fires per token)."""
	return _gap_series(recorder, run_id, "publish", "assistant:delta")


def all_flush_gaps(recorder, run_ids) -> list:
	out = []
	for rid in run_ids:
		out.extend(flush_gap_series(recorder, rid))
	return out


def all_publish_gaps(recorder, run_ids) -> list:
	out = []
	for rid in run_ids:
		out.extend(publish_gap_series(recorder, rid))
	return out


def dwell_series(gateway, run_ids) -> list:
	"""C4: per-run gateway dwell (ack -> lane admit), the main-lane queueing
	proxy under the simulated maxConcurrent cap."""
	out = []
	for rid in run_ids:
		tl = gateway.timeline(rid)
		if tl:
			d = tl.dwell_ms()
			if d is not None:
				out.append(d)
	return out


def ack_to_first_frame_series(gateway, run_ids) -> list:
	out = []
	for rid in run_ids:
		tl = gateway.timeline(rid)
		if tl:
			d = tl.ack_to_first_frame_ms()
			if d is not None:
				out.append(d)
	return out


# --------------------------------------------------------------------------- #
# C6 live canary — REAL RQ jobs + Desk HTTP
# --------------------------------------------------------------------------- #

# Module-level RQ job targets (must be importable by the worker process).


def _canary_job(token: str, enqueued_ms: int) -> None:
	import frappe

	frappe.cache().set_value(f"harness:canary:{token}", int(time.time() * 1000), expires_in_sec=180)


def _filler_job(work_ms: int, token: str) -> None:
	"""Real occupancy: a little DB work + a bounded sleep, to hold an RQ worker
	the way a chat turn holds one. Models chat-worker occupancy for C6."""
	import frappe

	try:
		frappe.db.count("Jarvis Chat Message")
	except Exception:
		pass
	time.sleep(max(0, work_ms) / 1000.0)
	try:
		frappe.cache().set_value(f"harness:filler:{token}", int(time.time() * 1000), expires_in_sec=180)
	except Exception:
		pass


def _enqueue_canary(queue_name: str) -> dict:
	import frappe

	token = uuid.uuid4().hex[:12]
	enq_ms = int(time.time() * 1000)
	frappe.enqueue(
		"jarvis.tests.harness.probes._canary_job",
		queue=queue_name,
		token=token,
		enqueued_ms=enq_ms,
		job_id=f"harness-canary-{token}",
	)
	# poll for execution
	deadline = time.time() + 65
	start_ms = None
	while time.time() < deadline:
		v = frappe.cache().get_value(f"harness:canary:{token}")
		if v:
			start_ms = int(v)
			break
		time.sleep(0.05)
	if start_ms is None:
		return {"queue": queue_name, "wait_ms": None, "starved": True}
	return {"queue": queue_name, "wait_ms": max(0, start_ms - enq_ms), "starved": (start_ms - enq_ms) > 60000}


def desk_http_probe(url: str, host: str) -> dict:
	req = urllib.request.Request(url, headers={"Host": host})
	t0 = time.monotonic()
	try:
		with urllib.request.urlopen(req, timeout=15) as r:
			code = getattr(r, "status", r.getcode())
			r.read(256)
		return {"ok": True, "code": code, "ms": (time.monotonic() - t0) * 1000.0}
	except Exception as e:
		return {"ok": False, "err": str(e), "ms": (time.monotonic() - t0) * 1000.0}


class CanaryProbe:
	"""Every ``cadence_s`` (default 10, per C6): a short + long RQ canary and a
	Desk HTTP GET, timing the wait. Runs in its own thread + frappe connection."""

	def __init__(self, site: str, *, cadence_s: float = 10.0, desk_url: str, desk_host: str):
		self.site = site
		self.cadence_s = cadence_s
		self.desk_url = desk_url
		self.desk_host = desk_host
		self._stop = threading.Event()
		self._thread = None
		self.samples: list[dict] = []
		self._lock = threading.Lock()

	def _loop(self) -> None:
		import frappe

		frappe.init(site=self.site)
		frappe.connect()
		try:
			while not self._stop.is_set():
				t_wall = time.time()
				short = _enqueue_canary("short")
				long_ = _enqueue_canary("long")
				desk = desk_http_probe(self.desk_url, self.desk_host)
				with self._lock:
					self.samples.append({"t": t_wall, "short": short, "long": long_, "desk": desk})
				self._stop.wait(self.cadence_s)
		finally:
			frappe.destroy()

	def start(self) -> "CanaryProbe":
		self._thread = threading.Thread(target=self._loop, name="harness-canary", daemon=True)
		self._thread.start()
		return self

	def stop(self) -> None:
		self._stop.set()
		if self._thread:
			self._thread.join(timeout=70)

	def series(self) -> dict:
		with self._lock:
			s = list(self.samples)
		return {
			"short_wait_ms": [x["short"]["wait_ms"] for x in s],
			"long_wait_ms": [x["long"]["wait_ms"] for x in s],
			"desk_ms": [x["desk"]["ms"] for x in s if x["desk"].get("ok")],
			"desk_failures": sum(1 for x in s if not x["desk"].get("ok")),
			"starved": sum(1 for x in s if x["short"].get("starved") or x["long"].get("starved")),
			"count": len(s),
		}


def background_flood(site: str, n: int, *, queue_name: str = "jarvis_chat", work_ms: int = 800) -> list[str]:
	"""Enqueue n real filler jobs to occupy RQ workers (C6 load). Returns the
	tokens (for optional completion tracking)."""
	import frappe

	tokens = []
	for _ in range(n):
		token = uuid.uuid4().hex[:12]
		frappe.enqueue(
			"jarvis.tests.harness.probes._filler_job",
			queue=queue_name,
			work_ms=work_ms,
			token=token,
			job_id=f"harness-filler-{token}",
		)
		tokens.append(token)
	return tokens


# --------------------------------------------------------------------------- #
# stop-click -> visible-stop (SUX-12)
# --------------------------------------------------------------------------- #


def measure_stop_visible(gateway, *, cadence_ms: float = 25.0, abort_after_frames: int = 2) -> dict:
	"""Start an abort-transcript turn, let a few frames stream, send chat.abort
	from a SECOND connection (web process aborting the worker's run), and
	measure the time to the visible aborted terminal."""
	from jarvis.chat.openclaw_client import OpenclawSession, OpenclawUnreachableError

	run_id = f"stopvis-{uuid.uuid4().hex[:8]}"
	gateway.arm(run_id, "abort", cadence_ms=cadence_ms)
	sess = OpenclawSession.connect(gateway.ws_url)
	try:
		sk = sess.create_session()
		ack = sess.chat_send(sk, "export please", run_id)
		t_abort = None
		stop_ms = None
		seen = 0
		for ev in sess.relay_turn_events(sk, ack.get("runId") or run_id, soft_deadline_s=10):
			kind = ev.get("kind")
			if kind in ("assistant", "tool"):
				seen += 1
				if seen == abort_after_frames and t_abort is None:
					t_abort = time.monotonic()
					s2 = OpenclawSession.connect(gateway.ws_url)
					try:
						s2.chat_abort(sk)
					finally:
						s2.close()
			if str(kind or "").startswith("relay:"):
				if t_abort is not None:
					stop_ms = (time.monotonic() - t_abort) * 1000.0
				return {"terminal": kind, "state": ev.get("state"), "stop_visible_ms": stop_ms}
		return {"terminal": None, "stop_visible_ms": None}
	except OpenclawUnreachableError as e:
		return {"terminal": "unreachable", "error": str(e), "stop_visible_ms": None}
	finally:
		sess.close()
