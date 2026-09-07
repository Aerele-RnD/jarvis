"""Best-effort source revision details for this Jarvis checkout."""

import subprocess
from functools import lru_cache
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
_GIT_TIMEOUT_SECONDS = 2


@lru_cache(maxsize=1)
def source_details() -> dict[str, str | None]:
	"""Return the checked-out branch and exact release tag, when Git can prove them.

	Packaged installs and detached checkouts may have neither value. Those are reported as
	``None`` rather than inferred from ``__version__`` so support never sees a made-up revision.
	"""
	return {
		"branch": _git_value("branch", "--show-current"),
		"tag": _git_value("describe", "--tags", "--exact-match", "--match", "v[0-9]*", "HEAD"),
	}


def _git_value(*args: str) -> str | None:
	try:
		result = subprocess.run(
			["git", "-C", str(_REPOSITORY_ROOT), *args],
			capture_output=True,
			text=True,
			timeout=_GIT_TIMEOUT_SECONDS,
			check=False,
		)
	except (OSError, subprocess.TimeoutExpired):
		return None
	if result.returncode:
		return None
	return result.stdout.strip() or None
