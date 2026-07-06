"""Compiler sanitizer for mined values (plan sections 6.3, 7 T4).

Every value the compiler interpolates into a pushed skill body is a MINED
string (customer/supplier/group names, realized config values) - attacker-
influenceable if a customer names a record to smuggle instructions. Templates
never grant authority to interpolated values, but a value that LOOKS like an
instruction (``ignore previous...``, a fenced code block, a forged
``<available_skills>`` tag, a ``jarvis__*`` tool call) is replaced with a
placeholder + "sanitized" badge rather than embedded verbatim (the acknowledged
ceiling: adversarial-but-valid data survives escaping - human review is the
backstop).

Pure and frappe-free, so the whole corpus is unit-testable without a site.
"""

from __future__ import annotations

import re

# Cap on a single interpolated value (plan: backtick-wrapped values <= 80 chars).
MAX_VALUE_LEN = 80
# Cap on an exemplar list (plan: exemplar lists <= 10).
MAX_EXEMPLARS = 10

# Shown in place of a value that trips the injection scan.
SANITIZED_PLACEHOLDER = "(value hidden - failed safety scan)"

# C0/C1 control chars except we handle whitespace via split(); DEL included.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Instruction-shaped strings (plan section 6.3): ignore-previous, a role prefix
# like ``system:``, a markdown/code fence, a jarvis tool-call token, a forged
# skills-listing tag, or a line that STARTS with ``#`` (heading) or ``---``
# (frontmatter / horizontal rule). The last two are multiline-anchored so an
# embedded newline still trips them.
_INJECTION_PATTERNS = (
	re.compile(r"ignore\s+(?:all\s+|the\s+|any\s+)?previous", re.IGNORECASE),
	re.compile(r"disregard\s+(?:all\s+|the\s+|any\s+)?(?:previous|above)", re.IGNORECASE),
	re.compile(r"(?im)^\s*(?:system|assistant|developer)\s*:"),
	re.compile(r"```"),
	re.compile(r"jarvis__"),
	re.compile(r"<\s*/?\s*available_skills\s*>", re.IGNORECASE),
	re.compile(r"(?m)^\s*#"),
	re.compile(r"(?m)^\s*---"),
)


def scan_instruction_injection(value) -> bool:
	"""True if ``value`` looks like a smuggled instruction (see module doc)."""
	if value is None:
		return False
	text = value if isinstance(value, str) else str(value)
	if not text:
		return False
	return any(p.search(text) for p in _INJECTION_PATTERNS)


def sanitize_value(value) -> str:
	"""One safe, single-line, <=80-char token for backtick-wrapped interpolation.

	Strips control chars, collapses ALL whitespace (newlines included) to single
	spaces, neutralizes backticks (so a value can never close/open a markdown
	code span), and caps length. Does NOT itself scan for injection - callers
	use :func:`scan_instruction_injection` first and swap in the placeholder.
	"""
	if value is None:
		return ""
	text = value if isinstance(value, str) else str(value)
	text = _CONTROL_RE.sub("", text)
	# Collapse any run of whitespace (incl. embedded newlines/tabs) to one space.
	text = " ".join(text.split())
	# Backtick-safe: the compiled bullet wraps values in backticks.
	text = text.replace("`", "'")
	if len(text) > MAX_VALUE_LEN:
		text = text[: MAX_VALUE_LEN - 3].rstrip() + "..."
	return text


def safe_value(value) -> str:
	"""Injection-scan then sanitize: the placeholder for a flagged value, else
	the sanitized token. The one call the compiler uses per interpolation."""
	if scan_instruction_injection(value):
		return SANITIZED_PLACEHOLDER
	return sanitize_value(value)


def sanitize_exemplars(values, cap: int = MAX_EXEMPLARS) -> list[str]:
	"""Sanitize a list of exemplar values: injection-flagged -> placeholder,
	empties dropped, capped at ``cap`` (plan: exemplar lists <= 10)."""
	out: list[str] = []
	for v in values or []:
		if len(out) >= cap:
			break
		if scan_instruction_injection(v):
			out.append(SANITIZED_PLACEHOLDER)
			continue
		sv = sanitize_value(v)
		if sv:
			out.append(sv)
	return out
