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

# Shared budget for the admin-sync background jobs (single-model + pool).
# One constant, three consumers, one invariant chain:
#
#   RQ envelope > worst-case work it wraps, AND lock TTL >= RQ envelope.
#
# Worst-case pool work: <=60s redis-lock wait + up to 3 POST attempts x 120s
# admin HTTP budget (post_update_llm_pool) + 2x5s retry sleeps ~= 430s.
# Worst-case single-model work: <=60s lock wait + 90s admin HTTP budget +
# the post-restart skills resyncs. 600s clears both with headroom, so the
# rq SIGALRM (JobTimeoutException) only fires on something genuinely
# wedged - not on a routine cold provision (JARVIS-2026-07-08, fault c).
#
# The lock TTL must be >= the RQ envelope: the TTL bounds how long a
# CRASHED holder can block others, but a healthy holder may legitimately
# run right up to its SIGALRM - a shorter TTL would expire mid-run and
# let a second sync mutate the container in parallel with the first,
# exactly the interleaving the lock exists to prevent.
ADMIN_SYNC_RQ_TIMEOUT_S = 600
ADMIN_SYNC_LOCK_TIMEOUT_S = ADMIN_SYNC_RQ_TIMEOUT_S

# Lock-acquisition waits for the sync workers. A dead (SIGKILLed/OOMed)
# holder blocks the lock for up to the full TTL (600s) - nothing releases
# the key early in that case - so the retry chain's CUMULATIVE wait must
# exceed the TTL or a fresh tenant's first sync can exhaust every attempt
# against a corpse and strand on a terminal "failed: skipped". Chain:
# primary 60s + 4 retries x 150s = 660s > 600s TTL. Each retry runs in its
# own fresh RQ envelope, and per-attempt lock wait + POST-ONLY work must
# fit that envelope. POST-only worst case (lock wait excluded - the wait
# is the other term of the sum): pool = 3x120s attempts + 2x5s sleeps
# = 370s; single-model = 90s + skills resyncs. So 150s + 370s = 520s
# <= 600s. These are the SAME figures the budget test in
# test_unified_llm_config.TestOnboardingAuditFixes asserts - tune the
# waits and the test together, and against the POOL figure (the larger
# of the two paths).
ADMIN_SYNC_PRIMARY_LOCK_WAIT_S = 60.0
ADMIN_SYNC_RETRY_LOCK_WAIT_S = 150.0
ADMIN_SYNC_LOCK_RETRIES = 4


def _commit_terminal_sync_status() -> None:
    """Make a terminal last_sync_* write durable - ONLY in a real worker.

    Frappe's execute_job wraps every background job in "rollback on any
    exception", which silently reverted uncommitted terminal statuses back
    to 'pending:' when the rq SIGALRM fired (JARVIS-2026-07-08, fault c) -
    hence the explicit commit. But enqueue(now=True) (tests and the
    run_admin_sync_inline path) invokes the worker via frappe.call, OUTSIDE
    execute_job: there is no rollback to defeat there, and committing would
    break FrappeTestCase transaction isolation (leaking every fixture write
    of the calling test). frappe.local.job is set exclusively by
    execute_job, so it is the exact "real worker" signal to gate on.

    Also commits under frappe.flags.in_migrate: when Redis is down during
    a bench migrate, frappe.enqueue falls back to frappe.call - outside
    execute_job, so frappe.local.job is unset - yet a later exception in
    the same migrate transaction would roll the terminal write back.
    Committing mid-migrate is normal (the patch runner itself commits
    between patches)."""
    if getattr(frappe.local, "job", None) or frappe.flags.in_migrate:
        frappe.db.commit()


def _sync_lock_wait_s(retry_left: int) -> float:
    """Lock wait for a sync attempt: short primary, longer retries."""
    return (
        ADMIN_SYNC_PRIMARY_LOCK_WAIT_S
        if retry_left >= ADMIN_SYNC_LOCK_RETRIES
        else ADMIN_SYNC_RETRY_LOCK_WAIT_S
    )


def _schedule_sync_lock_retry(*, method: str, job_base: str, retry_left: int,
                              **enqueue_kwargs) -> None:
    """Shared lock-loss retry scheduling for BOTH sync workers.

    One implementation so the retry-chain length, waits, status message,
    and job-id scheme can never silently diverge between the pool and the
    single-model paths (divergence re-arms the "stranded on failed:
    skipped" failure for whichever path missed the tuning).

    Writes the retry-pending status, then enqueues the next chain level:
    - Per-LEVEL job id: this still-running job holds its own id, so
      reusing it would be dedup-dropped and the chain would stop.
    - Per-CHAIN random suffix: two independently-triggered chains can
      reach the same level while the earlier one's job is still
      queued/started; a level-only id would dedup-drop the newer chain's
      retry, stranding its "pending: waiting..." status with no job
      working on it. Uniqueness makes an occasional duplicate run instead
      - harmless: workers re-read CURRENT settings and serialize on the
      redis lock.
    """
    settings = frappe.get_single("Jarvis Settings")
    settings.db_set(
        "last_sync_status",
        "pending: waiting for a concurrent sync to finish (will retry)",
        update_modified=False,
    )
    frappe.enqueue(
        method,
        queue="long",
        timeout=ADMIN_SYNC_RQ_TIMEOUT_S,
        job_id=f"{job_base}:retry:{retry_left - 1}:{frappe.generate_hash(length=6)}",
        deduplicate=True,
        retry_left=retry_left - 1,
        **enqueue_kwargs,
    )


class JarvisSettings(Document):
    def before_validate(self):
        """Mirror models[0] into legacy fields BEFORE validate() runs.

        This ensures _validate_auth_mode_requirements sees fresh auth mode +
        api_key from the models table, not stale legacy fields.
        Only mirrors when models table has at least one enabled row.

        Note: llm_provider isn't needed by _validate_auth_mode_requirements;
        kept in db_set (in _on_update_unified_llm) to avoid in-memory drift.
        It is NOT mirrored here to avoid _validate_selects rejecting the pool
        model's internal provider ID (e.g. "openai_compat"). The db_set in
        _on_update_unified_llm bypasses validation and writes the internal ID.
        """
        if not getattr(self, "models", None):
            return
        enabled = [m for m in self.models if m.enabled]
        if not enabled:
            return
        m0 = enabled[0]
        cred_type = (
            m0.credential_type if hasattr(m0, "credential_type")
            else (m0.get("credential_type") if hasattr(m0, "get") else "api_key")
        ) or "api_key"
        # Mirror auth mode so _validate_auth_mode_requirements sees the right mode.
        self.llm_auth_mode = cred_type
        # Mirror api_key in-memory so _validate_auth_mode_requirements sees it.
        # The encrypted write happens in on_update.
        # Guard: if get_password raises (decrypt error on a previously saved row),
        # skip the mirror silently rather than crashing through save().
        if cred_type == "api_key":
            from jarvis.jarvis.pool_serialize import _get_password
            try:
                api_key_val = _get_password(m0, "api_key")
            except Exception:
                api_key_val = None  # leave prior encrypted value; skip mirror
            if api_key_val and not (getattr(self, "llm_api_key", None) and not self.is_dummy_password(self.llm_api_key or "")):
                self.llm_api_key = api_key_val

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
        self._validate_pattern_window()

    def _validate_pattern_window(self):
        """Behavioural-learning window must be at least 1 hour when enabled.

        Wrap-aware: start > end is legal and means the window crosses
        midnight (e.g. 23:00-03:00). start == end reads as zero-length,
        not 24 hours. Engine status fields (pattern_last_run_at etc.) are
        written via db_set(update_modified=False) and never pass through
        here or _classify_llm_change.
        """
        if not frappe.utils.cint(getattr(self, "pattern_learning_enabled", 0)):
            return
        # Model-layer defense: behavioural learning is managed-only. The API and
        # the scheduler tick already bail on self-host; refusing enablement here
        # closes the Desk-form path (the feature never runs on self-host anyway).
        try:
            from jarvis import selfhost

            if selfhost.is_self_hosted():
                frappe.throw(
                    "Behavioural learning is available on managed plans only.",
                    frappe.ValidationError,
                )
        except ImportError:
            pass
        start = getattr(self, "pattern_window_start", None)
        end = getattr(self, "pattern_window_end", None)
        if not start or not end:
            frappe.throw(
                "Pattern learning requires both an analysis window start and end time.",
                frappe.ValidationError,
            )

        def seconds_of_day(value) -> int:
            # Time fields surface as "HH:MM:SS" strings or timedelta
            # depending on load path; get_time normalizes both.
            t = frappe.utils.get_time(str(value))
            return t.hour * 3600 + t.minute * 60 + t.second

        duration = (seconds_of_day(end) - seconds_of_day(start)) % (24 * 3600)
        if duration < 3600:
            frappe.throw(
                "The pattern learning analysis window must be at least 1 hour long "
                "(a start after the end is allowed - the window crosses midnight).",
                frappe.ValidationError,
            )

    def _validate_auth_mode_requirements(self):
        """Each auth mode requires its own credential field.

        REV-1: oauth/subscription mode has no bench-side credential
        requirement - openclaw owns the credential blob on the container.

        Scope: this validates ONLY the legacy single-model DIRECT path (the
        flat ``llm_*`` fields, with no ``models`` rows and no ``preset``).
        When the models table or a preset is present the config is unified -
        ``validate_models()`` (run in ``on_update``) owns credential
        validation, and the flat ``llm_*`` fields are only a derived mirror
        that ``before_validate`` populates for an ENABLED row. Re-checking that
        mirror here would race it and throw spuriously for a disabled-only
        table, a bare preset, or a ``models[0]`` decrypt error.

        For the legacy path, an unconfigured/pre-onboarding Settings (no model,
        no base_url, no connected oauth account) is skipped so unrelated saves
        (e.g. enabling sandbox mode during onboarding) aren't blocked - even
        though ``llm_auth_mode`` DEFAULTS to ``api_key`` before anything is
        chosen. ``reset_onboarding`` leaves ``llm_provider`` at a default but
        clears model/base_url/key, so it correctly reads as unconfigured.
        """
        # Unified config (any models rows or a preset) -> validate_models owns it.
        if getattr(self, "models", None) or getattr(self, "preset", None):
            return

        # Legacy direct path: only enforce once a real direct config exists.
        # llm_base_url covers custom-endpoint configs where llm_model is blank;
        # llm_oauth_connected_at is the canonical oauth signal (is_ready_for_chat
        # keys off it too), not the display-only llm_oauth_account_email.
        configured = bool(
            (getattr(self, "llm_model", None) or "")
            or (getattr(self, "llm_base_url", None) or "")
            or getattr(self, "llm_oauth_connected_at", None)
        )
        if not configured:
            return

        def is_password_set(fieldname: str) -> bool:
            in_memory = getattr(self, fieldname, None) or ""
            if in_memory and not self.is_dummy_password(in_memory):
                return True
            db_value = self.get_password(fieldname, raise_exception=False)
            return bool(db_value)

        mode = getattr(self, "llm_auth_mode", None) or "api_key"
        if mode == "api_key" and not is_password_set("llm_api_key"):
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
        # ------------------------------------------------------------------ #
        # Unified LLM path (2026-06-26): models table rows or preset present.
        # ------------------------------------------------------------------ #
        has_models = bool(getattr(self, "models", None))
        has_preset = bool(getattr(self, "preset", None))

        if has_models or has_preset:
            self._on_update_unified_llm()
            return

        # ------------------------------------------------------------------ #
        # Back-compat (legacy path): no models rows, no preset.
        # Runs the existing single-model classify/sync path unchanged.
        # Reset any stale proxy flags so UI/workers don't think it's in
        # pool mode (handles the proxy→direct transition when all models
        # are removed).
        # ------------------------------------------------------------------ #
        self.db_set("proxy_active", 0, update_modified=False)
        self.db_set("proxy_recommended", 0, update_modified=False)
        self._on_update_single_model_legacy()

    def _on_update_unified_llm(self):
        """New LLM path: validate → derive proxy_active/proxy_recommended →
        mirror models[0] into legacy fields → route to proxy or single-model path.

        Runs when the models table has rows OR a preset is set.
        Validate fires BEFORE any mutation so that errors surface clean without
        partially applying state.
        """
        from jarvis.jarvis.pool_serialize import (
            build_pool_payload,
            compute_proxy_active,
            validate_models,
        )

        # Step 1: Validate first — clean error before any state mutation.
        errors = validate_models(self)
        if errors:
            frappe.throw("<br>".join(errors), title="LLM Configuration")

        # Step 2: Compute and persist derived flags (read-only, no modified bump).
        proxy_active = compute_proxy_active(self)
        enabled_models = [m for m in (self.models or []) if m.enabled]
        proxy_recommended = (len(enabled_models) == 1 and not bool(getattr(self, "preset", None)))
        self.db_set("proxy_active", 1 if proxy_active else 0, update_modified=False)
        self.db_set("proxy_recommended", 1 if proxy_recommended else 0, update_modified=False)

        # Step 3: Mirror models[0] into the read-only legacy fields so that
        # the chat worker + onboarding gate continue to read llm_model / llm_auth_mode
        # correctly in direct (single-model) mode.
        if enabled_models:
            m0 = enabled_models[0]
            cred_type = (
                m0.credential_type if hasattr(m0, "credential_type")
                else (m0.get("credential_type") if hasattr(m0, "get") else "api_key")
            ) or "api_key"
            legacy_updates = {
                "llm_provider": (m0.provider if hasattr(m0, "provider") else m0.get("provider", "")) or "",
                "llm_model":    (m0.model    if hasattr(m0, "model")    else m0.get("model", ""))    or "",
                "llm_base_url": (m0.base_url if hasattr(m0, "base_url") else m0.get("base_url", "")) or "",
                "llm_auth_mode": cred_type,
            }
            for field, value in legacy_updates.items():
                self.db_set(field, value, update_modified=False)
            # Mirror api_key secret for api_key mode via the encrypted path.
            # IMPORTANT: db_set on a Password field writes PLAINTEXT into Singles
            # (it bypasses Frappe's __Auth encryption). Use set_encrypted_password
            # so the secret is stored in the __Auth table, never in plaintext.
            if cred_type == "api_key":
                from jarvis.jarvis.pool_serialize import _get_password
                from frappe.utils.password import set_encrypted_password
                api_key_val = _get_password(m0, "api_key")
                if api_key_val:
                    set_encrypted_password(
                        "Jarvis Settings", "Jarvis Settings",
                        api_key_val, "llm_api_key",
                    )
                    # Mask in-memory so nothing downstream re-writes plaintext.
                    self.llm_api_key = "*" * 10

        # Step 4: Route to proxy or single-model path.
        if proxy_active:
            # Proxy path: enqueue the admin call. The worker re-reads
            # Jarvis Settings at run time so no snapshot is needed here.
            # validate_models() already ran above (Step 1) so we know the
            # current config is clean before enqueuing.
            self._enqueue_pool_sync()
        else:
            # Single-model path (1 model, no preset): reset any stale proxy
            # flags so UI/workers don't think the tenant is still in pool mode.
            # (proxy_active/proxy_recommended were already written above in step 2,
            # but we explicitly reset here in case a tenant removed all models
            # and routed to the legacy path instead of the unified path.)
            self.db_set("proxy_active", 0, update_modified=False)
            self.db_set(
                "proxy_recommended",
                1 if (len(enabled_models) == 1) else 0,
                update_modified=False,
            )
            # Single-model path: reuse the existing classify/enqueue path.
            # The legacy fields are now mirrored, so _classify_llm_change
            # will correctly see any structural change.
            self._on_update_single_model_legacy()

    def _enqueue_pool_sync(self) -> None:
        """Enqueue the pool-sync admin call for the proxy path.

        Mirrors the existing ``on_update`` enqueue pattern:
        - Writes a ``pending:`` status synchronously so the UI can render
          "provisioning..." immediately.
        - Runs inline under ``frappe.flags.in_test`` so tests see the final
          status without polling.
        - Uses a stable ``job_id`` + ``deduplicate=True`` so two close-together
          saves coalesce into one worker invocation.
        - The worker re-reads Jarvis Settings at run time (no snapshot args),
          so a correction saved while the first job is still queued is
          naturally included when the job eventually executes.
        - Admin errors are caught and written to ``last_sync_status``; the
          save is never aborted on an admin failure.
        """
        self.db_set("last_sync_status", "pending: provisioning container (pool)",
                    update_modified=False)
        run_inline = bool(frappe.flags.in_test or frappe.flags.run_admin_sync_inline)
        # Budget rationale lives on ADMIN_SYNC_RQ_TIMEOUT_S.
        frappe.enqueue(
            "jarvis.jarvis.doctype.jarvis_settings.jarvis_settings"
            "._enqueued_sync_via_admin_pool",
            queue="long",
            timeout=ADMIN_SYNC_RQ_TIMEOUT_S,
            enqueue_after_commit=not run_inline,
            now=run_inline,
            job_id="jarvis_settings_sync:pool",
            deduplicate=True,
        )

    def _on_update_single_model_legacy(self):
        """The existing single-model on_update logic, extracted for reuse."""
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
        # Budget rationale lives on ADMIN_SYNC_RQ_TIMEOUT_S.
        frappe.enqueue(
            "jarvis.jarvis.doctype.jarvis_settings.jarvis_settings"
            "._enqueued_sync_via_admin",
            queue="long",
            timeout=ADMIN_SYNC_RQ_TIMEOUT_S,
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

        Sprint-3 (2026-06-16 review): the previous shape silently swallowed
        AdminRateLimitedError (logged only; last_sync_status stayed at
        "pending: ..." forever). The UI poller spins on that, never showing
        the user a state they can act on. Now the rate-limit branch ALSO
        writes a terminal failure status with the admin-provided
        retry_after_seconds hint so the UI can render a retry timer.

        Additionally a try/finally backstop guarantees last_sync_status
        never stays at "pending: ..." on an unexpected exception path -
        the UI poller flips off pending no matter what blew up.
        """
        from jarvis import admin_client
        terminal_written = False
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
            # Commit EVERY terminal status (ok and each failed branch), not
            # just the finally-backstop: the rq SIGALRM can fire at any
            # later point in this job (log_error, lock release, skills
            # resync), and execute_job's rollback would silently revert an
            # uncommitted terminal write back to "pending:" - the stuck
            # status this whole block exists to prevent.
            _commit_terminal_sync_status()
            terminal_written = True
            # A "restart" means the container may be freshly (re)provisioned
            # (rebind / reboot recovery / image upgrade) with an EMPTY
            # custom_skills/ AND learned_skills/. Re-push the customer's custom
            # skills and the compiled learned skills so a rebuilt container
            # repopulates them from the DB - no manual re-save needed.
            if action == "restart":
                self._resync_custom_skills_after_restart()
                self._resync_learned_skills_after_restart()
        except admin_client.AdminAuthError as e:
            self.db_set({
                "last_sync_at": frappe.utils.now(),
                "last_sync_status": f"failed: auth: {e}",
            })
            _commit_terminal_sync_status()
            terminal_written = True
            frappe.log_error(
                title="Jarvis: admin auth failed",
                message=frappe.get_traceback(),
            )
        except admin_client.AdminUnreachableError as e:
            self.db_set({
                "last_sync_at": frappe.utils.now(),
                "last_sync_status": f"failed: admin unreachable: {e}",
            })
            _commit_terminal_sync_status()
            terminal_written = True
            frappe.log_error(
                title="Jarvis: admin unreachable",
                message=frappe.get_traceback(),
            )
        except admin_client.AdminRateLimitedError as e:
            retry = e.retry_after_seconds or 0
            retry_str = f"retry_after={retry}s" if retry > 0 else "retry shortly"
            self.db_set({
                "last_sync_at": frappe.utils.now(),
                "last_sync_status": f"failed: rate-limited; {retry_str}",
            })
            _commit_terminal_sync_status()
            terminal_written = True
            frappe.logger().info(
                f"admin_client: rate-limited; retry_after={retry}s"
            )
        finally:
            # Final backstop: if a non-Admin* exception path blew through
            # (network exception class admin_client doesn't translate,
            # rq JobTimeoutException, programmer error, etc.) the status
            # would otherwise stay 'pending: ...' indefinitely. Flip it to
            # a terminal failure so the UI poller stops spinning.
            #
            # The commit is load-bearing (JARVIS-2026-07-08, fault c): the
            # exception keeps propagating after this finally, and Frappe's
            # execute_job catches it with frappe.db.rollback() - an
            # UNcommitted status write here is silently undone and the
            # status sticks at "pending:" forever. Committing makes the
            # terminal write durable before the rollback runs.
            if not terminal_written:
                try:
                    self.db_set({
                        "last_sync_at": frappe.utils.now(),
                        "last_sync_status": "failed: unexpected error; see Error Log",
                    })
                    _commit_terminal_sync_status()
                except Exception:
                    # If even the status write fails, swallow - we're
                    # already in an error path and re-raising would mask
                    # the real exception.
                    pass

    def _resync_custom_skills_after_restart(self) -> None:
        """Re-push the customer's custom skills to a (re)provisioned container.

        On a container rebuild the per-container ``custom_skills/`` is empty, so
        the durable ``Jarvis Custom Skill`` rows must be re-pushed. Enqueued (the
        same deduped job the SPA "save" uses) so it runs after this restart and
        does its own container restart. No-op when there are no custom skills, so
        customers without skills never pay an extra restart.
        """
        try:
            if not frappe.db.count("Jarvis Custom Skill"):
                return
            frappe.db.set_single_value(
                "Jarvis Settings", "custom_skills_sync_status",
                "pending: applying skills", update_modified=False,
            )
            frappe.enqueue(
                "jarvis.chat.custom_skills_api._enqueued_push_custom_skills",
                queue="long", timeout=180,
                job_id="jarvis_custom_skills_push", deduplicate=True,
            )
        except Exception:
            frappe.log_error(
                title="Jarvis: custom-skills resync after restart failed",
                message=frappe.get_traceback(),
            )

    def _resync_learned_skills_after_restart(self) -> None:
        """Re-push the compiled learned skills to a (re)provisioned container.

        The learned-namespace sibling of ``_resync_custom_skills_after_restart``
        (Behavioural Pattern Learning Phase 2): on a container rebuild the
        per-container ``learned_skills/`` is empty, so the managed
        ``Jarvis Custom Skill`` rows (``managed_by_learning=1`` - the durable
        bench-side storage) must be re-pushed through the dedicated learned
        chain. Enqueued (the same deduped job Apply uses) so it runs after this
        restart and does its own container restart. No-op when there are no
        managed rows, so customers without learned skills never pay an extra
        restart.
        """
        try:
            if not frappe.db.count("Jarvis Custom Skill", {"managed_by_learning": 1}):
                return
            frappe.db.set_single_value(
                "Jarvis Settings", "learned_skills_sync_status",
                "pending: applying learned skills", update_modified=False,
            )
            frappe.enqueue(
                "jarvis.chat.learned_skills_api._enqueued_push_learned_skills",
                queue="long", timeout=180,
                job_id="jarvis_learned_skills_push", deduplicate=True,
            )
        except Exception:
            frappe.log_error(
                title="Jarvis: learned-skills resync after restart failed",
                message=frappe.get_traceback(),
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


# Auto-retry transient pool-provisioning failures. The fleet-agent can 500
# ("admin unreachable: … agent_error: Internal Server Error") on a first cold
# provision that succeeds moments later (e.g. a sidecar not yet healthy within
# the health-poll window). A bounded retry self-heals the hiccup so it never
# strands the customer at the Connect-AI step. Only AdminUnreachableError (the
# 502/agent_error/connection class) is retried; auth/validation are terminal.
_POOL_SYNC_RETRIES = 3
_POOL_SYNC_RETRY_DELAY_S = 5


def _post_pool_with_retry(spec, api_keys, oauth_blobs):
    """post_update_llm_pool, retrying only the transient AdminUnreachableError.
    Re-raises the last unreachable error after exhausting retries; other Admin*
    errors propagate immediately (not retried)."""
    import time as _time
    import frappe as _frappe
    from jarvis import admin_client

    last = None
    for attempt in range(_POOL_SYNC_RETRIES):
        try:
            return admin_client.post_update_llm_pool(
                spec=spec, api_keys=api_keys, oauth_blobs=oauth_blobs,
            )
        except admin_client.AdminUnreachableError as e:
            last = e
            _frappe.logger().warning(
                f"jarvis_settings: pool sync unreachable "
                f"(attempt {attempt + 1}/{_POOL_SYNC_RETRIES}): {e}"
            )
            if attempt < _POOL_SYNC_RETRIES - 1 and not _frappe.flags.in_test:
                _time.sleep(_POOL_SYNC_RETRY_DELAY_S)
    raise last


def _enqueued_sync_via_admin_pool(retry_left: int = ADMIN_SYNC_LOCK_RETRIES) -> None:
    """Background-queue wrapper for the proxy (pool) sync path.

    Re-reads Jarvis Settings at run time and rebuilds the pool payload via
    ``build_pool_payload``. This means a correction saved while the first
    job is still queued is naturally included when the job eventually runs —
    the dedup (fixed job_id + deduplicate=True) drops the duplicate job but
    the single job that executes always sees the LATEST committed config.

    Mirrors the Redis-lock + error-handling pattern of ``_enqueued_sync_via_admin``
    so admin failures set last_sync_status (terminal) without aborting the save.

    Sprint-3 hardening (matching single-model path):
    - Redis lock prevents parallel pool + creds calls racing on the container.
    - AdminRateLimitedError writes a terminal failure with retry hint.
    - try/finally backstop ensures the status never sticks at "pending:".

    ``retry_left``: losing the lock race must not strand a FRESH tenant on a
    terminal "failed: skipped" (their first pool apply would never happen and
    is_ready_for_chat would gate them out of chat indefinitely). Each loss
    re-enqueues a follow-up run under its own job_id with a longer lock wait,
    down a chain sized so the CUMULATIVE wait outlives even a dead holder's
    full lock TTL (see ADMIN_SYNC_LOCK_RETRIES); only the last loss is
    terminal.
    """
    import frappe as _frappe
    from jarvis._redis_lock import redis_lock
    from jarvis import admin_client
    from jarvis.jarvis.pool_serialize import build_pool_payload

    with redis_lock(
        "jarvis_settings_admin_sync",
        # TTL must cover a healthy holder running to its rq SIGALRM - see
        # ADMIN_SYNC_LOCK_TIMEOUT_S. A 120s TTL under a 600s job would
        # expire mid-run and admit a concurrent container mutation.
        timeout_s=ADMIN_SYNC_LOCK_TIMEOUT_S,
        blocking_timeout_s=_sync_lock_wait_s(retry_left),
    ) as acquired:
        if not acquired:
            settings = _frappe.get_single("Jarvis Settings")
            if retry_left > 0:
                _frappe.logger().warning(
                    "jarvis_settings: pool admin sync lost the lock race; "
                    "scheduling retry (%d left)", retry_left - 1,
                )
                _schedule_sync_lock_retry(
                    method="jarvis.jarvis.doctype.jarvis_settings.jarvis_settings"
                           "._enqueued_sync_via_admin_pool",
                    job_base="jarvis_settings_sync:pool",
                    retry_left=retry_left,
                )
                return
            _frappe.logger().warning(
                "jarvis_settings: skipping pool admin sync; "
                "another worker held the lock past blocking timeout (retries exhausted)",
            )
            settings.db_set(
                "last_sync_status",
                "failed: skipped (concurrent sync did not finish in time)",
                update_modified=False,
            )
            return

        # Re-read CURRENT settings at run time (not a snapshot from job args)
        # so a correction saved between enqueue and execution is included.
        settings = _frappe.get_single("Jarvis Settings")

        # Re-validate: the config may have changed between enqueue and run.
        # If no longer proxy-valid, skip the push.
        from jarvis.jarvis.pool_serialize import validate_models, compute_proxy_active
        revalidation_errors = validate_models(settings)
        if revalidation_errors or not compute_proxy_active(settings):
            reason = "; ".join(revalidation_errors) if revalidation_errors else "not proxy_active"
            settings.db_set(
                "last_sync_status",
                f"skipped: no longer proxy-valid after re-read ({reason})",
                update_modified=False,
            )
            return

        spec, api_keys, oauth_blobs = build_pool_payload(settings)

        terminal_written = False
        try:
            result = _post_pool_with_retry(spec, api_keys, oauth_blobs) or {}
            resolved_action = result.get("action", "pool_update")
            settings.db_set({
                "last_sync_at": _frappe.utils.now(),
                "last_sync_status": f"ok ({resolved_action} via admin)",
                # Durable "this pool has been APPLIED to the container at
                # least once" marker. is_ready_for_chat gates pool tenants
                # on it: proxy_active alone is config INTENT (committed
                # synchronously at save, before this job runs) and must not
                # be read as provisioning success - a fresh tenant whose
                # first sync is still pending/failed has no working pool.
                "llm_pool_synced_at": _frappe.utils.now(),
            })
            # Commit every terminal write - matching _sync_via_admin; see
            # the comment there. Also makes llm_pool_synced_at durable.
            _commit_terminal_sync_status()
            terminal_written = True
        except admin_client.AdminAuthError as e:
            settings.db_set({
                "last_sync_at": _frappe.utils.now(),
                "last_sync_status": f"failed: auth: {e}",
            })
            _commit_terminal_sync_status()
            terminal_written = True
            _frappe.log_error(
                title="Jarvis: admin auth failed (pool sync)",
                message=_frappe.get_traceback(),
            )
        except admin_client.AdminUnreachableError as e:
            settings.db_set({
                "last_sync_at": _frappe.utils.now(),
                "last_sync_status": f"failed: admin unreachable: {e}",
            })
            _commit_terminal_sync_status()
            terminal_written = True
            _frappe.log_error(
                title="Jarvis: admin unreachable (pool sync)",
                message=_frappe.get_traceback(),
            )
        except admin_client.AdminRateLimitedError as e:
            retry = e.retry_after_seconds or 0
            retry_str = f"retry_after={retry}s" if retry > 0 else "retry shortly"
            settings.db_set({
                "last_sync_at": _frappe.utils.now(),
                "last_sync_status": f"failed: rate-limited; {retry_str}",
            })
            _commit_terminal_sync_status()
            terminal_written = True
            _frappe.logger().info(
                f"admin_client: pool sync rate-limited; retry_after={retry}s"
            )
        except admin_client.AdminValidationError as e:
            settings.db_set({
                "last_sync_at": _frappe.utils.now(),
                "last_sync_status": f"failed: validation: {e}",
            })
            _commit_terminal_sync_status()
            terminal_written = True
            _frappe.log_error(
                title="Jarvis: admin validation failed (pool sync)",
                message=_frappe.get_traceback(),
            )
        finally:
            # Commit is load-bearing - see the matching backstop in
            # _sync_via_admin. Without it, a propagating exception (rq
            # JobTimeoutException in particular: the pool POST alone may
            # consume the whole HTTP budget) reaches execute_job's
            # frappe.db.rollback() and the terminal write is undone,
            # pinning the UI poller on "pending:" forever
            # (JARVIS-2026-07-08, fault c).
            if not terminal_written:
                try:
                    settings.db_set({
                        "last_sync_at": _frappe.utils.now(),
                        "last_sync_status": "failed: unexpected error; see Error Log",
                    })
                    _commit_terminal_sync_status()
                except Exception:
                    pass


def _enqueued_sync_via_admin(action: str, retry_left: int = ADMIN_SYNC_LOCK_RETRIES) -> None:
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

    with redis_lock(
        "jarvis_settings_admin_sync",
        # TTL must cover a healthy holder running to its rq SIGALRM - see
        # ADMIN_SYNC_LOCK_TIMEOUT_S. A 120s TTL under a 600s job would
        # expire mid-run and admit a concurrent container mutation.
        timeout_s=ADMIN_SYNC_LOCK_TIMEOUT_S,
        blocking_timeout_s=_sync_lock_wait_s(retry_left),
    ) as acquired:
        if not acquired:
            settings = frappe.get_single("Jarvis Settings")
            if retry_left > 0:
                # Same retry chain as the pool worker: a sibling sync may
                # now legitimately hold the lock for minutes (600s
                # envelope), so a single 60s wait + terminal "failed:
                # skipped" would silently DROP this credential change -
                # chat would keep running on the old key with only a
                # status line to notice.
                frappe.logger().warning(
                    "jarvis_settings: admin sync (action=%s) lost the lock "
                    "race; scheduling retry (%d left)", action, retry_left - 1,
                )
                _schedule_sync_lock_retry(
                    method="jarvis.jarvis.doctype.jarvis_settings.jarvis_settings"
                           "._enqueued_sync_via_admin",
                    job_base=f"jarvis_settings_sync:{action}",
                    retry_left=retry_left,
                    action=action,
                )
                return
            frappe.logger().warning(
                "jarvis_settings: skipping admin sync (action=%s); "
                "another worker held the lock past blocking timeout (retries exhausted)",
                action,
            )
            settings.db_set(
                "last_sync_status",
                "failed: skipped (concurrent sync did not finish in time)",
                update_modified=False,
            )
            return
        settings = frappe.get_single("Jarvis Settings")
        settings._sync_via_admin(action)
