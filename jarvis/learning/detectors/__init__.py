"""Static detector SQL + postprocess functions (plan section 4.2).

One module per domain. Each module holds:
  * named SQL template constants - SELECT-only, ``%(param)s`` placeholders
    ONLY, ``docstatus = 1`` for submittables, aggregated to UNIT grain (one
    row per independent unit: parent document, party, or month) so the
    executor never counts child-table rows;
  * optional ``postprocess_*`` functions for master-vs-realized (S5),
    existence, and multi-source merges (naming series) that the generic
    reduce cannot express.

Fence discipline (plan section 5.4): these modules never call
``frappe.db.sql`` / ``.save`` / ``.insert`` / ``set_user``. SQL runs through
the executor's :class:`PatternDB` facade inside the engine's READ ONLY
transaction; postprocess functions receive that same facade and read through
it too. A CI grep-ban enforces this.
"""
