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

        # OAuth-token change detection — same masked/plaintext logic as llm_api_key.
        for fname in ("llm_oauth_refresh_token", "llm_oauth_access_token"):
            self.flags[f"{fname}_changed"] = self._password_field_changed(fname)

        # Plain Select field — direct change comparison via has_value_changed.
        self.flags.llm_auth_mode_changed = bool(self.has_value_changed("llm_auth_mode"))

        self._validate_auth_mode_requirements()

    def _password_field_changed(self, fieldname: str) -> bool:
        """Return True if `fieldname` (a Password field) carries a new value in this save.

        Mirrors the llm_api_key detection logic: in-memory must be non-empty
        plaintext and differ from the pre-save snapshot.
        """
        current = getattr(self, fieldname, None) or ""
        if not current or self.is_dummy_password(current):
            return False
        old = self.get_doc_before_save()
        old_value = (getattr(old, fieldname, None) or "") if old else ""
        return current != old_value

    def _validate_auth_mode_requirements(self):
        """Each auth mode requires its own credential field.

        For Password fields, Frappe masks the value before validate() runs on
        an unchanged save, so we treat "already persisted in DB" as 'is set'.
        """
        def is_password_set(fieldname: str) -> bool:
            in_memory = getattr(self, fieldname, None) or ""
            # Treat a non-empty, non-masked in-memory value as set
            if in_memory and not self.is_dummy_password(in_memory):
                return True
            # Or fall back to whatever is persisted in the DB
            db_value = self.get_password(fieldname, raise_exception=False)
            return bool(db_value)

        mode = getattr(self, "llm_auth_mode", None) or "api_key"
        if mode == "api_key":
            if not is_password_set("llm_api_key"):
                frappe.throw(
                    "API-key auth mode requires llm_api_key",
                    frappe.ValidationError,
                )
        elif mode == "subscription":
            if not is_password_set("llm_oauth_refresh_token"):
                frappe.throw(
                    "Subscription auth mode requires an OAuth refresh token. "
                    "Connect a chat subscription in Onboarding.",
                    frappe.ValidationError,
                )

    def _resolve_llm_secret_for_push(self) -> str:
        """Return the bytes to push to openclaw based on auth mode.

        Subscription mode: the short-lived OAuth access token (rotated by
        the refresh cron). API-key mode: the long-lived API key. Used by
        both the bench's _sync_via_admin and (via openclaw_push) the local
        push path.
        """
        field = (
            "llm_oauth_access_token"
            if (self.llm_auth_mode or "api_key") == "subscription"
            else "llm_api_key"
        )
        return self.get_password(field, raise_exception=False) or ""

    def on_update(self):
        # Mode-switch hygiene: clear the opposite mode's credentials so we
        # don't leave stale tokens that could be misused if the user toggles
        # back later.
        self._on_mode_switch_clear_opposite_creds()
        action = self._classify_llm_change()
        if action is None:
            return
        # Dispatch: admin path (prod) when the customer has an admin api token
        # (set by onboarding); otherwise the Phase 1 local-openclaw_push path
        # (dev). Keyed on the api token, not jarvis_admin_url — onboarding sets
        # the token but leaves jarvis_admin_url blank (admin_client falls back to
        # the hardcoded DEFAULT_ADMIN_URL).
        if (self.get_password("jarvis_admin_api_key", raise_exception=False) or "").strip():
            self._sync_via_admin(action)
        else:
            self._sync_via_local_openclaw(action)

    def _sync_via_admin(self, action: str) -> None:
        """Prod path: route LLM creds through admin → fleet → openclaw container.

        ``action`` is the classifier output ("reload" / "restart"):
        - "reload" calls post_rotate_llm_secret (hot-rotate /secrets/llm.key,
          no container restart) — used for OAuth access-token rotation by
          the bench-side cron and for plain api_key rotation by manual save.
        - "restart" calls post_update_llm_creds (re-render openclaw.json
          with auth_mode + restart container) — used for mode switches,
          provider/model/base_url changes, refresh-token re-auth.

        Errors land in last_sync_status so the customer's save never fails
        because of admin issues; they can always retry.
        """
        from jarvis import admin_client
        try:
            if action == "reload":
                secret = self._resolve_llm_secret_for_push()
                result = admin_client.post_rotate_llm_secret(secret=secret) or {}
                resolved_action = result.get("action", "reload")
            else:  # "restart"
                secret = self._resolve_llm_secret_for_push()
                result = admin_client.post_update_llm_creds(
                    provider=self.llm_provider or "",
                    model=self.llm_model or "",
                    base_url=self.llm_base_url or "",
                    api_key=secret,
                    auth_mode=self.llm_auth_mode or "api_key",
                ) or {}
                resolved_action = result.get("action", "restart")
            self.db_set({
                "last_sync_at": frappe.utils.now(),
                "last_sync_status": f"ok ({resolved_action} via admin)",
            })
        except admin_client.AdminAuthError as e:
            self.db_set("last_sync_status", f"failed: auth: {e}")
            frappe.log_error(
                title="Jarvis: admin auth failed",
                message=frappe.get_traceback(),
            )
        except admin_client.AdminUnreachableError as e:
            self.db_set("last_sync_status", f"failed: admin unreachable: {e}")
            frappe.log_error(
                title="Jarvis: admin unreachable",
                message=frappe.get_traceback(),
            )
        except admin_client.AdminRateLimitedError as e:
            # Rate-limit means our cron is calling too often — bench-side bug.
            # Don't mutate last_sync_status (creds are fine); just log + return.
            frappe.logger().info(
                f"admin_client: rate-limited; retry_after={e.retry_after_seconds}s"
            )

    def _sync_via_local_openclaw(self, action: str) -> None:
        """Phase 1 dev path: push creds directly to a locally-running openclaw
        container via openclaw_push (WebSocket secrets.reload or docker restart).

        Skipped silently when operator config is incomplete (e.g. bootstrap
        hasn't run yet).
        """
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
        - 'reload': credential-only rotation (api_key, oauth_access_token,
          or oauth_refresh_token-alone); hot reload via secrets.reload.
        - 'restart': structural change (mode switch, provider/model/base_url);
          re-render config + restart.

        Refresh-token rotation alone is treated as a reload because the
        container never sees refresh tokens — they're bench bookkeeping.
        When a provider rotates both refresh and access tokens together,
        the access-token-changed flag drives the action, not refresh.
        """
        # Structural triggers — any of these means we need a full restart.
        if self.flags.get("llm_auth_mode_changed"):
            return "restart"

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

        # Credential-only rotations — Password fields detected via self.flags,
        # which is set in validate() before _save_passwords() masks the values.
        if self.flags.get("llm_api_key_changed"):
            return "reload"
        if self.flags.get("llm_oauth_access_token_changed"):
            return "reload"
        # Refresh-token alone is bench bookkeeping — container doesn't see it.
        # We still need to route through the bench's "reload" path so the
        # last_sync_status reflects the save and the cron's fail-counter
        # clears. Hitting the rotate endpoint is harmless (the secret being
        # pushed is the current access token, unchanged).
        if self.flags.get("llm_oauth_refresh_token_changed"):
            return "reload"

        return None

    def _on_mode_switch_clear_opposite_creds(self):
        """When llm_auth_mode flips, wipe the now-unused credential set."""
        if not self.flags.get("llm_auth_mode_changed"):
            return
        from frappe.utils.password import remove_encrypted_password
        if self.llm_auth_mode == "subscription":
            # Going to subscription — clear API-key residue.
            remove_encrypted_password("Jarvis Settings", "Jarvis Settings", "llm_api_key")
        elif self.llm_auth_mode == "api_key":
            # Going to api_key — clear all OAuth state. db_set on a Password field
            # writes plaintext to the column; remove_encrypted_password only clears
            # __Auth. We need both for a clean wipe.
            for f in ("llm_oauth_refresh_token", "llm_oauth_access_token"):
                remove_encrypted_password("Jarvis Settings", "Jarvis Settings", f)
                self.db_set(f, None, update_modified=False)
            for f in ("llm_oauth_access_token_expires_at", "llm_oauth_account_email",
                      "llm_oauth_connected_at", "llm_oauth_last_refresh_at"):
                self.db_set(f, None, update_modified=False)
