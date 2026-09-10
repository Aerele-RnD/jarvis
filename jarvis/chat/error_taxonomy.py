"""Chat failure classification, using the same ordered rules as all chat UIs.

Rules are deliberately conservative: unrecognized text retains the legacy
``gateway`` code, whose copy no longer claims a transient or local cause.
"""

import json
import re
from pathlib import Path

# A JSON literal exported as an ES module works with Frappe's esbuild 0.14
# and Node without JSON import attributes. Parse data only; never execute JS.
_RULE_DATA = (Path(__file__).parents[1] / "public/js/turn_error_rules.mjs").read_text(encoding="utf-8")
_RULES = [
	(rule["code"], re.compile(rule["pattern"], re.IGNORECASE))
	for rule in json.loads(_RULE_DATA.split("export default ", 1)[1].rstrip().removesuffix(";"))
]


def classify_error_text(raw) -> str:
	text = json.dumps(raw) if isinstance(raw, (dict, list)) else str(raw or "")
	return next((code for code, pattern in _RULES if pattern.search(text)), "gateway")
