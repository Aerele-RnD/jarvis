import frappe
from frappe.model.document import Document

LLM_FIELDS_TRIGGERING_SYNC = (
    "llm_provider",
    "llm_model",
    "llm_api_key",
    "llm_base_url",
)

OPERATOR_FIELDS_FOR_RELOAD = (
    "agent_url",
    "agent_token",
    "agent_llm_key_path",
)

OPERATOR_FIELDS_FOR_RESTART = OPERATOR_FIELDS_FOR_RELOAD + (
    "agent_config_path",
    "agent_compose_dir",
)


class JarvisSettings(Document):
    def validate(self):
        # Detect a new llm_api_key before _save_passwords() masks it to '****'.
        # Strategy: the field is changed only when the current value is a non-dummy
        # (real plaintext) value that differs from the value in the pre-save snapshot.
        # If both are plaintext and equal (e.g. seeded via db_set in tests), no change.
        # If both are dummy ('***'), the user didn't touch the field in this save.
        current_key = getattr(self, "llm_api_key", None) or ""
        if not current_key or self.is_dummy_password(current_key):
            # Field is empty or masked — user didn't supply a new value in this save.
            self.flags.llm_api_key_changed = False
        else:
            # Field has a real plaintext value.  Compare against the pre-save snapshot
            # to determine if it was actually changed (vs. just loaded from DB as
            # plaintext because db_set was used to seed it without encryption).
            old = self.get_doc_before_save()
            old_key = (getattr(old, "llm_api_key", None) or "") if old else ""
            # If the old value is also plaintext and identical, no change.
            self.flags.llm_api_key_changed = current_key != old_key

    def on_update(self):
        action = self._classify_llm_change()
        if action is None:
            return

        required = OPERATOR_FIELDS_FOR_RESTART if action == "restart" else OPERATOR_FIELDS_FOR_RELOAD
        missing = [f for f in required if not (getattr(self, f, None) or "").strip()]
        if missing:
            self.db_set(
                "last_sync_status",
                "skipped: operator config incomplete; run jarvis.openclaw_bootstrap.start first",
            )
            return

        try:
            if action == "reload":
                from jarvis import openclaw_push
                openclaw_push.push_creds_reload(self)
            elif action == "restart":
                from jarvis import openclaw_push
                token = self.get_password("agent_token") or ""
                openclaw_push.push_creds_restart(self, token)
            self.db_set({
                "last_sync_at": frappe.utils.now(),
                "last_sync_status": f"ok ({action})",
            })
        except Exception as e:
            frappe.log_error(
                title="Jarvis: openclaw push failed",
                message=frappe.get_traceback(),
            )
            self.db_set("last_sync_status", f"failed: {type(e).__name__}: {e}")

    def _classify_llm_change(self) -> str | None:
        """Return one of: None | 'reload' | 'restart'.

        - None: no LLM field changed; no action needed.
        - 'reload': only llm_api_key changed; hot reload via secrets.reload.
        - 'restart': provider/model/base_url changed; re-render config + restart.
        """
        old = self.get_doc_before_save()
        if old is None:
            # First-ever save: treat as restart only if at least one of provider/model is set now
            if any(getattr(self, f, None) for f in ("llm_provider", "llm_model", "llm_base_url")):
                return "restart"
            if getattr(self, "llm_api_key", None):
                return "reload"
            return None

        # Non-password fields: direct string comparison.
        structural_fields = ("llm_provider", "llm_model", "llm_base_url")
        structural_changed = any(
            (getattr(self, f, None) or "") != (getattr(old, f, None) or "")
            for f in structural_fields
        )
        if structural_changed:
            return "restart"

        # Password field (llm_api_key): by the time on_update runs, _save_passwords() has
        # already masked the field to '***...' on self.  A real new key would have been
        # unmasked (non-dummy) at validate() time.  We detect the change via self.flags,
        # which is set in validate() before the masking occurs.
        if self.flags.get("llm_api_key_changed"):
            return "reload"

        return None
