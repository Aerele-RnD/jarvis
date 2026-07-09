"""Guard: every @frappe.whitelist method must have fully type-annotated
parameters.

jarvis/hooks.py declares ``require_type_annotated_api_methods = True``. On a
Frappe that enforces it, an UN-annotated parameter on a whitelisted method
500s the request before the function body runs. The local dev bench's Frappe
does not enforce the flag, so the bug is invisible here and detonates only on
freshly-deployed strict benches - exactly how ``save_llm_pool(models, ...)``
took down onboarding in the JARVIS-2026-07-08 incident (fault a).

This sweep makes the contract testable on ANY Frappe: walk the app's API
modules, find every whitelisted function, and assert each parameter carries
an annotation.
"""

from __future__ import annotations

import importlib
import inspect

from frappe.tests.utils import FrappeTestCase

# The customer-facing API surface: modules whose whitelisted methods are hit
# by the SPA / onboarding wizard / plugin. Extend when adding a new module
# with @frappe.whitelist methods.
_API_MODULES = (
	"jarvis.onboarding",
	"jarvis.oauth.api",
	"jarvis.account",
	"jarvis.chat.api",
	"jarvis.api",
	"jarvis.diagnostics",
	"jarvis.selfhost",
	"jarvis.chat.device",
)


def _whitelisted_functions(module):
	# frappe.whitelist() registers the function in the global
	# ``frappe.whitelisted`` set (no attribute is stamped on the function),
	# so detection is set membership.
	import frappe

	for name, fn in vars(module).items():
		if callable(fn) and fn in frappe.whitelisted:
			# Only functions defined in THIS module (skip re-exports).
			if getattr(fn, "__module__", None) == module.__name__:
				yield name, fn


class TestWhitelistAnnotations(FrappeTestCase):
	def test_every_whitelisted_param_is_annotated(self):
		offenders = []
		found_any = False
		for modname in _API_MODULES:
			module = importlib.import_module(modname)
			for name, fn in _whitelisted_functions(module):
				found_any = True
				sig = inspect.signature(fn)
				for pname, param in sig.parameters.items():
					if pname in ("self", "cls"):
						continue
					if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
						continue
					if param.annotation is inspect.Parameter.empty:
						offenders.append(f"{modname}.{name}({pname})")
		self.assertTrue(found_any, "sweep found no whitelisted functions - "
						"module list or detection broke")
		self.assertFalse(
			offenders,
			"un-annotated @frappe.whitelist parameters (500 under Frappe's "
			"require_type_annotated_api_methods, which hooks.py enables): "
			+ ", ".join(offenders),
		)
