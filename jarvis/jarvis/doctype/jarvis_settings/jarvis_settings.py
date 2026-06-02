import frappe
from frappe.model.document import Document

LLM_FIELDS_TRIGGERING_SYNC = (
    "llm_provider",
    "llm_model",
    "llm_api_key",
    "llm_base_url",
)


# Subscription-mode auth modes - the container owns credentials, so the
# bench's classifier treats a save with no structural change as a no-op.
# We accept both "oauth" (REV-1 canonical) and the legacy "subscription"
# value migrated tenants might still carry.
_CONTAINER_OWNED_MODES = {"oauth", "subscription"}


class JarvisSettings(Document):
    def validate(self):
        # Detect a new llm_api_key before _save_passwords() masks it to '****'.
        current_key = getattr(self, "llm_api_key", None) or ""
        if not current_key or self.is_dummy_password(current_key):
            self.flags.llm_api_key_changed = False
        else:
            old = self.get_doc_before_save()
            old_key = (getattr(old, "llm_api_key", None) or "") if old else ""
            self.flags.llm_api_key_changed = current_key != old_key

        # Plain Select field - direct change comparison via has_value_changed.
        self.flags.llm_auth_mode_changed = bool(self.has_value_changed("llm_auth_mode"))

        self._validate_auth_mode_requirements()

    def _validate_auth_mode_requirements(self):
        """Each auth mode requires its own credential field.

        REV-1: oauth/subscription mode has no bench-side credential
        requirement - openclaw owns the credential blob on the container.
        """
        def is_password_set(fieldname: str) -> bool:
            in_memory = getattr(self, fieldname, None) or ""
            if in_memory and not self.is_dummy_password(in_memory):
                return True
            db_value = self.get_password(fieldname, raise_exception=False)
            return bool(db_value)

        mode = getattr(self, "llm_auth_mode", None) or "api_key"
        if mode == "api_key":
            if not is_password_set("llm_api_key"):
                frappe.throw(
                    "API-key auth mode requires llm_api_key",
                    frappe.ValidationError,
                )

    def _resolve_llm_secret_for_push(self) -> str:
        """Return the bytes to push to openclaw's llm.key.

        REV-1: only api_key mode pushes a secret. Oauth mode's credentials
        live in the container's auth-profiles.json - pushed via the separate
        push_oauth_blob path, not through this resolver.
        """
        return self.get_password("llm_api_key", raise_exception=False) or ""

    def on_update(self):
        action = self._classify_llm_change()
        if action is None:
            return
        # Unified architecture (post-2026-05-29): on_update always routes
        # through admin → fleet-agent → container. Local-dev runs admin +
        # fleet-agent on the same machine; there is no longer a bench-
        # local push shortcut. If admin isn't configured, _sync_via_admin
        # fails with AdminAuthError - the right error for "this workspace
        # isn't set up; run bootstrap_host then dev_onboard."
        self._sync_via_admin(action)

    def _sync_via_admin(self, action: str) -> None:
        """Prod path: route LLM creds through admin → fleet → openclaw container.

        ``action`` is the classifier output:
        - "reload" calls post_rotate_llm_secret (hot-rotate /secrets/llm.key
          for api-key rotation; no restart).
        - "restart" calls post_update_llm_creds (re-render openclaw.json
          and restart container) - used for mode switches and
          provider/model/base_url changes.
        """
        from jarvis import admin_client
        try:
            if action == "reload":
                secret = self._resolve_llm_secret_for_push()
                result = admin_client.post_rotate_llm_secret(secret=secret) or {}
                resolved_action = result.get("action", "reload")
            else:  # "restart"
                # In oauth mode the api_key body is empty - container reads
                # credentials from auth-profiles.json instead.
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
            frappe.logger().info(
                f"admin_client: rate-limited; retry_after={e.retry_after_seconds}s"
            )

    def _classify_llm_change(self) -> str | None:
        """Return one of: None | 'reload' | 'restart'.

        - None: no LLM field changed; no action needed (in oauth mode this
          is the common case - openclaw owns refresh).
        - 'reload': api_key rotation only; hot-reload via rotate-secret.
        - 'restart': structural change (mode switch, provider/model/base_url).
        """
        # Structural triggers.
        if self.flags.get("llm_auth_mode_changed"):
            return "restart"

        old = self.get_doc_before_save()
        if old is None:
            # First-ever save: treat as restart only if at least one of
            # provider/model is set now.
            if any(getattr(self, f, None) for f in ("llm_provider", "llm_model", "llm_base_url")):
                return "restart"
            if getattr(self, "llm_api_key", None):
                return "reload"
            return None

        structural_fields = ("llm_provider", "llm_model", "llm_base_url")
        structural_changed = any(
            (getattr(self, f, None) or "") != (getattr(old, f, None) or "")
            for f in structural_fields
        )
        if structural_changed:
            return "restart"

        # Credential-only rotations - api_key only in REV-1. OAuth tokens
        # are openclaw-owned and don't trip the classifier.
        if self.flags.get("llm_api_key_changed"):
            return "reload"

        return None
