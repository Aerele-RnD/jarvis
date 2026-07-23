"""after_install hook - seed what a fresh site cannot get any other way.

``install_app`` runs ``after_install`` but NEVER ``after_migrate``, and it marks
every patch complete without executing it (``frappe/installer.py``). So a site
that is installed and not yet migrated only has what DocType sync produced.

DocType sync auto-creates any role named in a permission row
(``core/doctype/doctype/doctype.py``), which covers "Jarvis User" (16 DocTypes),
"Jarvis Admin" (10) and "Jarvis Skill Reviewer" (1). Named in NO DocType, and so
absent on such a site before this hook existed:

  * "Knowledge Wiki Manager"  (wiki curator rights, wiki_permissions.py)
  * "Jarvis Support User" / "Jarvis Support Admin"  (support panel scope)

Observed live on a freshly reinstalled tenant: all three synced roles present,
all three of the above missing.

Reuses the migrate-time seeder rather than duplicating it, so the two entry
points cannot drift. Idempotent: every seeder inside is exists-guarded.

Mirrors ``jarvis_admin_v2/install.py``, which exists for the same reason.
"""

import frappe

from jarvis.learning.roles import after_migrate as seed_roles_and_settings


def after_install() -> None:
	seed_roles_and_settings()
	frappe.db.commit()
