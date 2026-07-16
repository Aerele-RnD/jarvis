"""Jarvis Trigger DocType controller.

A trigger attaches an action to a doc event on a target doctype: either a
deterministic sandboxed Python script (materialized as a MANAGED, always-
disabled Server Script that ``jarvis.triggers.engine`` dispatches itself) or a
background LLM evaluation. All user-facing validation lives here so it runs on
every insert/save whether the write came from the SPA API, the Desk, chat's
doc tools, or a test — mirroring ``Jarvis Macro``.

Managed Server Script contract:
  * name = "jarvis-trigger-" + trigger row-name; linked back via
    ``server_script`` (read_only — controller-owned).
  * ALWAYS ``disabled = 1``: core's server_script_map must skip it, the
    engine calls ``execute_doc`` itself so it fires exactly once (and only
    while the trigger is enabled).
  * Deleted when the action switches Script -> LLM and on trigger trash.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint
from frappe.utils.safe_exec import is_safe_exec_enabled

from jarvis.triggers.engine import (
	LLM_EVENTS,
	SCRIPT_EVENT_MAP,
	SUPPORTED_EVENTS,
	clear_cache,
	eval_context,
)

MAX_NAME_LEN = 140
MAX_LLM_INSTRUCTION_LEN = 4000
MAX_LLM_DAILY_CAP = 2000
DEFAULT_LLM_DAILY_CAP = 100

MANAGED_SCRIPT_PREFIX = "jarvis-trigger-"

# Doctypes a trigger may never target: self-referential loops (the trigger
# doctypes themselves), the managed-artifact doctype (Server Script), the
# log doctypes triggers themselves write (feedback storms), and the chat
# doctypes (every message would fire user automations).
DENYLISTED_DOCTYPES = frozenset({
	"Jarvis Trigger",
	"Jarvis Trigger Activity",
	"Server Script",
	"Error Log",
	"Webhook Request Log",
	"Jarvis Conversation",
	"Jarvis Chat Message",
})


class JarvisTrigger(Document):
	def validate(self):
		self._validate_name()
		self._validate_target_doctype()
		self._validate_event_action()
		self._validate_condition()
		if self.action_type == "Script":
			self._validate_script()
		else:
			self._validate_llm()

	def on_update(self):
		self._sync_server_script()
		self._notify_changed()

	def on_trash(self):
		self._delete_server_script(clear_link=False)
		self._notify_changed()

	# ------------------------------------------------------------------ #
	# validate
	# ------------------------------------------------------------------ #
	def _validate_name(self):
		self.trigger_name = (self.trigger_name or "").strip()
		if not self.trigger_name:
			frappe.throw(_("Trigger name is required."))
		if len(self.trigger_name) > MAX_NAME_LEN:
			frappe.throw(_("Trigger name must be at most {0} characters.").format(MAX_NAME_LEN))

	def _validate_target_doctype(self):
		if not self.target_doctype:
			frappe.throw(_("Target DocType is required."))
		row = frappe.db.get_value(
			"DocType", self.target_doctype, ["issingle", "istable"], as_dict=True
		)
		if not row:
			frappe.throw(_("DocType '{0}' does not exist.").format(self.target_doctype))
		if cint(row.issingle):
			frappe.throw(
				_("Triggers cannot target single DocTypes ('{0}' is a Single).").format(
					self.target_doctype
				)
			)
		if cint(row.istable):
			frappe.throw(
				_(
					"Triggers cannot target child tables ('{0}'). Target the parent "
					"DocType instead — child rows ride its events."
				).format(self.target_doctype)
			)
		if self.target_doctype in DENYLISTED_DOCTYPES:
			frappe.throw(
				_(
					"Triggers on '{0}' are not allowed — they could loop on their own "
					"logs or fire on internal plumbing."
				).format(self.target_doctype)
			)

	def _validate_event_action(self):
		if self.doc_event not in SUPPORTED_EVENTS:
			frappe.throw(_("Unsupported doc event: {0}").format(self.doc_event))
		if self.action_type not in ("Script", "LLM"):
			frappe.throw(_("Action type must be Script or LLM."))
		if self.action_type == "LLM" and self.doc_event not in LLM_EVENTS:
			frappe.throw(
				_(
					"LLM actions run in the background after the save commits, so "
					"they cannot attach to '{0}' (an in-transaction event). Use a "
					"Script action to block a save, or pick a post-event like "
					"After Save."
				).format(self.doc_event)
			)

	def _validate_condition(self):
		self.condition = (self.condition or "").strip()
		if not self.condition:
			return
		# Same check as frappe Webhook.validate_condition: compile + evaluate
		# against an empty doc of the target doctype with the webhook context.
		temp_doc = frappe.new_doc(self.target_doctype)
		try:
			frappe.safe_eval(self.condition, eval_locals=eval_context(temp_doc))
		except Exception as e:
			frappe.throw(_("Invalid Condition: {0}").format(str(e)))

	def _validate_script(self):
		if not (self.script_body or "").strip():
			frappe.throw(_("Script body is required for a Script action."))
		if not is_safe_exec_enabled():
			frappe.throw(
				_(
					"Server scripts are not enabled on this bench "
					"(server_script_enabled). Deterministic trigger actions need "
					"it; LLM actions work without it."
				)
			)
		from RestrictedPython import compile_restricted

		from frappe.utils.safe_exec import FrappeTransformer

		try:
			compile_restricted(self.script_body, policy=FrappeTransformer)
		except Exception as e:
			# Frappe core only msgprint-warns on Server Script compile errors;
			# a trigger script that cannot compile can never run, so throw.
			frappe.throw(_("Script does not compile: {0}").format(str(e)))

	def _validate_llm(self):
		instruction = (self.llm_instruction or "").strip()
		if not instruction:
			frappe.throw(_("LLM instruction is required for an LLM action."))
		if len(instruction) > MAX_LLM_INSTRUCTION_LEN:
			frappe.throw(
				_("LLM instruction must be at most {0} characters.").format(
					MAX_LLM_INSTRUCTION_LEN
				)
			)
		self.llm_instruction = instruction
		cap = cint(self.llm_daily_cap) or DEFAULT_LLM_DAILY_CAP
		self.llm_daily_cap = max(1, min(cap, MAX_LLM_DAILY_CAP))

	# ------------------------------------------------------------------ #
	# managed Server Script
	# ------------------------------------------------------------------ #
	def _sync_server_script(self):
		"""Materialize/refresh the managed Server Script (action Script) or
		remove it (action switched to LLM)."""
		if self.action_type != "Script":
			self._delete_server_script()
			return
		existing = (
			self.server_script
			if self.server_script and frappe.db.exists("Server Script", self.server_script)
			else None
		)
		ss = frappe.get_doc("Server Script", existing) if existing else frappe.new_doc("Server Script")
		ss.update({
			"script_type": "DocType Event",
			"reference_doctype": self.target_doctype,
			"doctype_event": SCRIPT_EVENT_MAP[self.doc_event],
			"script": self.script_body,
			# ALWAYS disabled: core's server_script_map skips disabled scripts,
			# so only jarvis.triggers.engine dispatches it (exactly once, and
			# only while the trigger is enabled).
			"disabled": 1,
		})
		# Server Script.validate() is only_for("Script Manager") — a Jarvis
		# Admin saving a trigger legitimately is not one. Skipping validate is
		# safe: _validate_script() above already compile-checked the body (and
		# throws where core only warns).
		ss.flags.ignore_validate = True
		if ss.is_new():
			ss.name = f"{MANAGED_SCRIPT_PREFIX}{self.name}"
			ss.insert(ignore_permissions=True)
		else:
			ss.save(ignore_permissions=True)
		if self.server_script != ss.name:
			self.db_set("server_script", ss.name, update_modified=False)

	def _delete_server_script(self, clear_link: bool = True):
		"""Delete the managed Server Script (ignore permissions/missing). The
		trigger's own Link is cleared FIRST so delete_doc's link check cannot
		block; on_trash skips the clear (the row is going away anyway)."""
		name = self.server_script or f"{MANAGED_SCRIPT_PREFIX}{self.name}"
		if clear_link and self.server_script:
			self.db_set("server_script", None, update_modified=False)
		frappe.delete_doc(
			"Server Script", name, ignore_permissions=True, ignore_missing=True, force=True
		)

	# ------------------------------------------------------------------ #
	# cache + realtime
	# ------------------------------------------------------------------ #
	def _notify_changed(self):
		clear_cache()
		# Best-effort nudge to the actor's own open tabs; other users pick the
		# change up on list refetch (a broadcast to every jarvis user would be
		# disproportionate for a settings-style doctype).
		try:
			from jarvis.chat.events import publish_to_user

			publish_to_user(frappe.session.user, {"kind": "trigger:changed"})
		except Exception:
			pass
