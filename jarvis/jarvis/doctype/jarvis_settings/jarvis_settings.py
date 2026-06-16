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
        # Async path (2026-06-09): a container restart can take 30-60s on
        # the admin side waiting for healthz to come back up. Blocking the
        # save call for that long stalls the onboarding UI and feels
        # broken. Instead, mark the status as "pending: ..." synchronously
        # so the UI can render a "provisioning..." state, then enqueue the
        # real admin call on the long queue. The UI polls
        # ``onboarding.get_llm_sync_status`` until the status flips from
        # ``pending:`` to ``ok ...`` or ``failed: ...``.
        pending_label = (
            "pending: provisioning container"
            if action == "restart"
            else "pending: rotating credentials"
        )
        self.db_set("last_sync_status", pending_label, update_modified=False)
        # In tests, run inline so existing assertions on the final status
        # don't have to poll. Set ``frappe.flags.run_admin_sync_inline``
        # from app code that needs the synchronous behavior (rare).
        run_inline = bool(
            frappe.flags.in_test or frappe.flags.run_admin_sync_inline
        )
        # Coalesce duplicate close-together saves: enqueue under a fixed
        # job_id keyed by the action. Two saves that produce the same
        # action within the worker-poll window resolve to one job. The
        # worker re-reads the doc fresh so it always sees the latest
        # committed state, not whatever was in flight when each save
        # fired. Different actions still both enqueue (one "reload" and
        # one "restart" are not the same op) but the in-worker Redis
        # lock makes them run serially, not interleaved.
        frappe.enqueue(
            "jarvis.jarvis.doctype.jarvis_settings.jarvis_settings"
            "._enqueued_sync_via_admin",
            queue="long",
            timeout=120,
            enqueue_after_commit=not run_inline,
            now=run_inline,
            job_id=f"jarvis_settings_sync:{action}",
            deduplicate=True,
            action=action,
        )

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

        ``flags.force_admin_sync`` (set by save_llm_creds(force=True))
        overrides the no-diff gate and always returns 'restart' so the
        complete_paste_signin path can re-render openclaw.json + restart
        the container even when nothing structural changed on the bench.
        """
        # Caller-forced sync (e.g. complete_paste_signin re-authorize):
        # bypass the diff gate so admin actually fires.
        if self.flags.get("force_admin_sync"):
            return "restart"
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


def _enqueued_sync_via_admin(action: str) -> None:
    """Background-queue wrapper: re-load Jarvis Settings + run _sync_via_admin.

    Loading a fresh Single is necessary because the queue worker runs in a
    separate request context - we can't pass the Document instance across
    the queue boundary safely.

    Updates ``last_sync_status`` from ``pending: ...`` to either
    ``ok (... via admin)`` or ``failed: ...`` - the UI polls
    ``onboarding.get_llm_sync_status`` to observe the transition.

    Sprint-2 (2026-06-16 review): serialize concurrent sync workers
    with a Redis lock. Two close saves on the same Single can still
    enqueue two jobs with different actions ("reload" then "restart");
    both must run, but they must NOT run in parallel - one calling
    post_rotate_llm_secret while the other calls post_update_llm_creds
    crosses container state in unpredictable ways. The lock yields one
    serial run; the late arrival waits up to 60s for the early one to
    finish, then runs against the now-current doc state.
    """
    from jarvis._redis_lock import redis_lock

    with redis_lock("jarvis_settings_admin_sync", timeout_s=120, blocking_timeout_s=60.0) as acquired:
        if not acquired:
            # Couldn't get the lock within 60s: an earlier sync is
            # apparently stuck. Log + bail; the failed status field
            # carries the diagnostic. Don't fight the holder.
            frappe.logger().warning(
                "jarvis_settings: skipping admin sync (action=%s); "
                "another worker held the lock past blocking timeout",
                action,
            )
            settings = frappe.get_single("Jarvis Settings")
            settings.db_set(
                "last_sync_status",
                "failed: skipped (concurrent sync did not finish in time)",
                update_modified=False,
            )
            return
        settings = frappe.get_single("Jarvis Settings")
        settings._sync_via_admin(action)
