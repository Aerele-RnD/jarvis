"""Shared dry-run sandbox for preview paths (api._run_preview, preview_doc).

Neutralizes commits, runs the body inside a savepoint, rolls back, and keeps
the before/after-commit callback queues clean - the four invariants a dry run
needs on MariaDB:

1. Commits must be no-ops for the duration: a real COMMIT releases ALL
   savepoints, which would both persist the write and break the rollback.
2. The savepoint must be created INSIDE the try whose finally restores
   ``db.commit`` - otherwise a savepoint failure (aborted connection) leaks
   the no-op commit for the rest of the request and later writes silently
   never persist.
3. The rollback must tolerate the savepoint being gone: a deadlock /
   lock-wait abort inside the body rolls back the WHOLE transaction and
   releases savepoints, so ``ROLLBACK TO SAVEPOINT`` raises 1305 - at which
   point there is nothing left to undo anyway.
4. ``before_commit`` / ``after_commit`` callbacks queued by the body (webhook
   and notification enqueues register there) must be dropped on exit: a
   savepoint rollback does NOT clear those queues, so without this they fire
   on the request's next real commit - an external webhook for a phantom,
   rolled-back document.

External side effects fired DIRECTLY inside a hook (an inline HTTP call, a
file write) are still not sandboxed - nothing can roll those back.
"""
from collections import deque
from contextlib import contextmanager

import frappe


@contextmanager
def preview_sandbox():
    """Run the body with every DB effect rolled back and nothing queued."""
    db = frappe.db
    real_commit = db.commit
    saved_queues = {
        name: tuple(getattr(db, name)._functions)
        for name in ("before_commit", "after_commit")
        if hasattr(db, name)
    }
    sp = "jps_" + frappe.generate_hash(length=10)  # pure; before any patching
    db.commit = lambda *args, **kwargs: None
    try:
        db.savepoint(sp)
        yield
    finally:
        db.commit = real_commit
        try:
            db.rollback(save_point=sp)
        except Exception:
            # Savepoint already released (full-transaction abort: deadlock /
            # lock-wait / connection failure) - the work is gone either way.
            pass
        for name, functions in saved_queues.items():
            getattr(db, name)._functions = deque(functions)
