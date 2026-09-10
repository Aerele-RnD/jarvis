"""Chat failure classification, using the same ordered rules as all chat UIs.

Rules are deliberately conservative: unrecognized text retains the legacy
``gateway`` code, whose copy no longer claims a transient or local cause.
"""

import json
import re
from pathlib import Path

# A JSON literal exported as an ES module works with Frappe's esbuild 0.14
# and Node without JSON import attributes. Parse data only; never execute JS.
_RULES_PATH = Path(__file__).parents[1] / "public/js/turn_error_rules.mjs"
# Anchored on the export and the closing "];" so a stray trailing comment or
# a reworded prefix fails loudly here (import time) with a clear message,
# instead of raising IndexError inside the turn's own error-reporting path.
_RULE_LITERAL = re.compile(r"^export default\s*(\[.*\])\s*;?\s*$", re.DOTALL | re.MULTILINE)


def _load_rules(path: Path) -> list[tuple[str, re.Pattern]]:
	match = _RULE_LITERAL.search(path.read_text(encoding="utf-8"))
	if not match:
		raise RuntimeError(f"{path.name}: expected 'export default [ ... ];' holding a JSON array")
	return [(rule["code"], re.compile(rule["pattern"], re.IGNORECASE)) for rule in json.loads(match.group(1))]


_RULES = _load_rules(_RULES_PATH)


def classify_error_text(raw) -> str:
	text = json.dumps(raw) if isinstance(raw, (dict, list)) else str(raw or "")
	return next((code for code, pattern in _RULES if pattern.search(text)), "gateway")
