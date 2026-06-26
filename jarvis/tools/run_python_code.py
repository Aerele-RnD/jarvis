"""Run agent-provided Python over a dataset in a resource-limited subprocess.

SECURITY: this executes arbitrary Python. It is hardened - a separate
frappe-free process, CPU/memory/file-size rlimits, restricted builtins, blocked
dangerous imports, wall-clock timeout, data passed in (no DB of its own) - but
Python sandboxing is NOT a hard boundary; notably it does not block network
egress at the OS level. So it is **OFF by default**: an operator opts a site in
via site_config ``jarvis_python_sandbox: true`` and should only do so on a
network-isolated bench. Intended for ad-hoc analysis over data the agent
already fetched (passed in as ``data``).
"""
import json
import os
import subprocess
import sys

import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

_RUNNER = os.path.join(os.path.dirname(__file__), "_python_sandbox.py")
_MAX_CODE = 20000
_MEM_MB = 512
_CPU_S = 5
_DEFAULT_TIMEOUT = 10
_MAX_TIMEOUT = 30


def run_python_code(code: str, data=None, timeout: int = 10) -> dict:
	"""Execute ``code`` in a sandboxed subprocess; return {ok, result, stdout, error}.

	``data`` is bound as a variable; set a variable named ``result`` to return a
	value (pandas DataFrame/Series are JSON-ified). ``pd`` / ``np`` are preloaded.
	No DB, network, or filesystem access. Disabled unless an operator enabled the
	sandbox for this site.
	"""
	if not frappe.conf.get("jarvis_python_sandbox"):
		raise PermissionDeniedError(
			"the Python sandbox is disabled for this site; an operator must set "
			"site_config 'jarvis_python_sandbox': true to enable it"
		)
	if not code or not isinstance(code, str):
		raise InvalidArgumentError("code (a Python string) is required")
	if len(code) > _MAX_CODE:
		raise InvalidArgumentError(f"code too long ({len(code)} chars; max {_MAX_CODE})")
	wall = max(1, min(int(timeout or _DEFAULT_TIMEOUT), _MAX_TIMEOUT))

	payload = json.dumps({"code": code, "data": data, "mem_mb": _MEM_MB, "cpu_s": _CPU_S})
	try:
		proc = subprocess.run(
			[sys.executable, _RUNNER],
			input=payload.encode("utf-8"),
			capture_output=True,
			timeout=wall,
			cwd="/tmp",
		)
	except subprocess.TimeoutExpired:
		raise InvalidArgumentError(f"code exceeded the {wall}s wall-clock limit")

	out = (proc.stdout or b"").decode("utf-8", "replace").strip()
	if not out:
		tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-400:]
		return {
			"ok": False,
			"error": "no output - the sandbox was killed (resource limit or crash)",
			"stderr": tail,
		}
	try:
		return json.loads(out)
	except ValueError:
		return {"ok": False, "error": "sandbox returned unparseable output", "raw": out[:2000]}
