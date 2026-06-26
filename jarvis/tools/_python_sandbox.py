"""Standalone subprocess sandbox runner for the run_python_code tool.

NOT imported by the bench - executed as a child process
(``python jarvis/tools/_python_sandbox.py``) with a JSON request on stdin. It
imports NO frappe. Reads {"code","data","mem_mb","cpu_s"}; runs the code under
OS resource limits + a restricted builtins/import environment; writes
{"ok","result","stdout","error"} JSON on stdout.

Defense-in-depth (separate process, rlimits, no frappe/DB, blocked dangerous
imports, no file writes) - NOT a hard boundary; Python can't be made fully
escape-proof in-process. Run only on an isolated bench.
"""
import contextlib
import io
import json
import sys

_BLOCKED_ROOTS = {
	"os", "sys", "subprocess", "socket", "shutil", "pathlib", "ctypes",
	"multiprocessing", "threading", "asyncio", "requests", "urllib", "http",
	"ftplib", "smtplib", "frappe", "importlib", "resource", "signal", "pty",
	"fcntl", "mmap", "tempfile", "glob", "pickle", "marshal", "code", "codeop",
	"webbrowser", "platform",
}

_orig_import = __import__


def _safe_import(name, *args, **kwargs):
	root = (name or "").split(".")[0]
	if root in _BLOCKED_ROOTS:
		raise ImportError(f"import of {root!r} is blocked in the sandbox")
	return _orig_import(name, *args, **kwargs)


def _set_limits(mem_mb, cpu_s):
	try:
		import resource

		nbytes = mem_mb * 1024 * 1024
		for res, val in (
			(resource.RLIMIT_AS, nbytes),
			(resource.RLIMIT_DATA, nbytes),
			(resource.RLIMIT_CPU, cpu_s),
			(resource.RLIMIT_FSIZE, 0),  # block file writes
		):
			try:
				resource.setrlimit(res, (val, val))
			except (ValueError, OSError):
				pass
	except Exception:
		pass


def _jsonable(v):
	try:
		json.dumps(v)
		return v
	except (TypeError, ValueError):
		pass
	try:
		import numpy as np

		if isinstance(v, np.generic):
			return v.item()
		if isinstance(v, np.ndarray):
			return v.tolist()
	except Exception:
		pass
	try:
		import pandas as pd

		if isinstance(v, pd.DataFrame):
			return [_jsonable(r) for r in v.to_dict(orient="records")]
		if isinstance(v, pd.Series):
			return {str(k): _jsonable(x) for k, x in v.to_dict().items()}
	except Exception:
		pass
	if isinstance(v, dict):
		return {str(k): _jsonable(x) for k, x in v.items()}
	if isinstance(v, (list, tuple)):
		return [_jsonable(x) for x in v]
	return str(v)


def main():
	req = json.loads(sys.stdin.read() or "{}")
	_set_limits(int(req.get("mem_mb") or 512), int(req.get("cpu_s") or 5))

	import builtins as _b

	unsafe = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint"}
	safe_builtins = {k: getattr(_b, k) for k in dir(_b) if k not in unsafe}
	safe_builtins["__import__"] = _safe_import

	ns = {"__builtins__": safe_builtins, "data": req.get("data"), "result": None}
	try:
		import numpy as np
		import pandas as pd

		ns.update({"pd": pd, "pandas": pd, "np": np, "numpy": np})
	except Exception:
		pass

	buf = io.StringIO()
	try:
		with contextlib.redirect_stdout(buf):
			exec(req.get("code") or "", ns)  # noqa: S102 - sandboxed by design
		payload = {
			"ok": True,
			"result": _jsonable(ns.get("result")),
			"stdout": buf.getvalue()[:20000],
		}
	except Exception as e:  # noqa: BLE001 - any failure is reported to the caller
		payload = {"ok": False, "error": f"{type(e).__name__}: {e}", "stdout": buf.getvalue()[:20000]}
	sys.stdout.write(json.dumps(payload, default=str))


if __name__ == "__main__":
	main()
