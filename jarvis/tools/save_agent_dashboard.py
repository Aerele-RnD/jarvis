"""``jarvis__save_agent_dashboard`` — Phase-4 delegate → saved Jarvis Dashboard.

An auditor/operator DELEGATE, after its evaluator has produced findings, authors
a compact, self-contained findings dashboard HTML (severity counts + each
finding's authored outcome text + ref + amount + citation) and persists it here.
The delegate builds the HTML; this tool lands it as a real ``Jarvis Dashboard``
the customer can open, and links it on the run.

This is the "Option A" wire: the delegate persists its OWN self-contained HTML
directly, so the bench never has to fetch a hosted canvas back out of the
container gateway (no fleet canvas-GET / admin relay). It reuses the SAME proven
identity path as ``record_agent_run``:

  * It runs impersonated as the run's ``run_as_user`` (the plugin dispatch
    resolved the caller's ``X-Jarvis-Session`` header to that user).
  * It resolves the ``Jarvis Agent Run`` from the CALLER's session_key
    (``Run.session_key`` — never a model-supplied id), so a delegate can only
    ever attach a dashboard to its OWN run, and only while the run is still
    ``running``. A call to an already-finalized run is an idempotent no-op that
    returns the run's existing dashboard.

A2 content contract: the HTML the delegate supplies must be OUTCOME-LEVEL text
only (what fired, on which doc, why it matters, the statutory citation) — never
rule ids/tokens, predicates, thresholds, or as-coded catalog text. The persisted
dashboard is a disclosure surface, governed by the same contract as the finding
writeback. The HTML renders inside the Dashboards page's CSP-locked, egress-
blocked sandbox iframe (same threat model as the chat canvas), so it may not
reach the network regardless of what the model emitted.
"""
from __future__ import annotations

import frappe

from jarvis.exceptions import InvalidArgumentError

RUN = "Jarvis Agent Run"
INSTALLATION = "Jarvis Agent Installation"


def save_agent_dashboard(
    html: str,
    title: str | None = None,
    description: str | None = None,
) -> dict:
    """Persist a delegate-authored findings dashboard and link it on the run.

    Args:
      html: the FULL self-contained HTML document (inline CSS/JS only, no
        external resources — it renders in the CSP-locked sandbox). A2: outcome
        text + citation only, never rule ids/thresholds.
      title: short dashboard title; defaults to "<agent> — <period>".
      description: optional one-line summary.

    Returns ``{run, dashboard, title}``. On an already-finalized run returns the
    run's existing dashboard (idempotent).
    """
    from jarvis.chat import agent_runs
    from jarvis.tools._agent_run_ctx import get_session_key

    if not (html or "").strip():
        raise InvalidArgumentError("save_agent_dashboard requires a non-empty html document")

    # The run is resolved from the CALLER's session bearer, never a model-supplied
    # id — so a delegate can only ever attach a dashboard to its own run.
    session_key = get_session_key()
    if not session_key:
        raise InvalidArgumentError(
            "save_agent_dashboard must be called by an agent delegate over its run "
            "session (no session_key in context)")

    run_row = frappe.db.get_value(
        RUN, {"session_key": session_key},
        ["name", "status", "installation", "dashboard"], as_dict=True,
    )
    if not run_row:
        raise InvalidArgumentError("no agent run is bound to this session")
    if run_row.status != "running":
        # Idempotency: the run already finalized — return its dashboard (if any)
        # without creating a second one.
        return {
            "run": run_row.name,
            "dashboard": run_row.dashboard or None,
            "idempotent": True,
            "note": "run already finalized; existing dashboard returned",
        }
    if not run_row.installation:
        raise InvalidArgumentError("run has no installation")
    if run_row.dashboard:
        # Already attached this run (a retried author step) — reuse it.
        return {"run": run_row.name, "dashboard": run_row.dashboard, "idempotent": True}

    inst = frappe.get_doc(INSTALLATION, run_row.installation)
    run_doc = frappe.get_doc(RUN, run_row.name)

    try:
        dashboard = agent_runs.persist_agent_dashboard(
            run_doc, inst, html, title=title, description=description
        )
    except frappe.ValidationError as e:
        # Caps/scope errors from the DocType controller — give the delegate a
        # clean, non-fatal message (the run's findings writeback still proceeds).
        raise InvalidArgumentError(str(e))
    frappe.db.commit()

    return {
        "run": run_doc.name,
        "dashboard": dashboard,
        "title": frappe.db.get_value("Jarvis Dashboard", dashboard, "dashboard_title"),
    }
