# Jarvis Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap the customer-side `jarvis` Frappe app — installable skeleton, single Settings DocType for tenant credentials, and a permission-aware tool handler module exposing `get_schema`, `get_doc`, `get_list`, and `run_report`. End state: an engineer can install the app on a Frappe v15 bench, set API credentials, and call each tool via a whitelisted endpoint, with every call enforcing the calling user's ERPNext permissions.

**Architecture:** Standard Frappe app layout under a `jarvis` module. Tools live in `jarvis/tools/` as plain Python functions. A central dispatcher (`jarvis/tools/registry.py`) maps tool names to callables, validates arguments, and routes through Frappe's permission system. A single whitelisted endpoint (`jarvis.api.call_tool`) exposes the dispatcher over HTTP so tools can be smoke-tested before the socket transport (Plan 2) exists. The Settings DocType (`Jarvis Settings`, type=Single) stores the openclaw API key and socket endpoint. No socket client, no chat UI, no openclaw cloud integration in this plan — those are explicitly later plans.

**Tech Stack:**
- Frappe Framework v15 (and ERPNext v15 for the test bench)
- Python 3.10+
- Frappe's built-in test runner (`FrappeTestCase`, `bench run-tests`)
- Standard Frappe app scaffolding (`hooks.py`, `modules.txt`, `pyproject.toml`)

**Spec reference:** `docs/superpowers/specs/2026-05-15-jarvis-design.md` (Layer 1, customer-side half).

---

## Prerequisites — Isolated Workspace

The whole project lives under `/Users/venkatesh/bench/develop/jarvis/`. Inside it, each concern has its own directory so this work is fully isolated from the workstation's other benches and projects.

```
/Users/venkatesh/bench/develop/jarvis/
├── docs/                       # specs and plans (this file lives here)
├── discuss/                    # ad-hoc working notes
├── bench/                      # isolated Frappe bench (Frappe develop branch + ERPNext)
│   ├── apps/jarvis -> ../../app   # symlink to the app source below
│   └── sites/jarvis.localhost     # the test site this plan uses
├── openclaw/                   # openclaw repo clone (https://github.com/openclaw/openclaw)
└── app/                        # the jarvis Frappe app source (pyproject.toml here)
```

Before Task 1, Task 0 (provisioning, performed by the controller) creates this structure:
- `bench init bench --frappe-branch develop`
- `cd bench && bench get-app erpnext --branch develop`
- `cd bench && bench new-site jarvis.localhost --install-app erpnext --admin-password admin --mariadb-root-password <local>`
- `git clone https://github.com/openclaw/openclaw openclaw`
- `mkdir app && ln -s /Users/venkatesh/bench/develop/jarvis/app /Users/venkatesh/bench/develop/jarvis/bench/apps/jarvis`

All `bench` commands in this plan assume the working directory is `/Users/venkatesh/bench/develop/jarvis/bench`. The `bench` CLI is on `PATH` at `/Users/venkatesh/.local/bin/bench`.

Wherever this plan says `jarvis.localhost`, use `jarvis.localhost`.

**Frappe version note:** Bench is initialized on the `develop` branch (Frappe 17-dev / ERPNext 17-dev) to match the workstation's main bench. The APIs used in this plan (`FrappeTestCase`, `frappe.has_permission`, `frappe.get_meta`, `frappe.get_list`, `frappe.desk.query_report.run`, DocType JSON, `hooks.py`) are stable across recent Frappe versions; no version-specific code is anticipated.

---

## File Structure

All files below live under `app/` (the Frappe app source root, symlinked into `bench/apps/jarvis`):

```
app/
├── pyproject.toml                              # app packaging
├── README.md                                   # one-paragraph stub
├── license.txt                                 # MIT
└── jarvis/                                     # the python package (== Frappe app name)
    ├── __init__.py                             # __version__
    ├── hooks.py                                # Frappe app registration
    ├── modules.txt                             # contains: Jarvis
    ├── patches.txt                             # empty, but required
    ├── api.py                                  # whitelisted call_tool endpoint
    ├── exceptions.py                           # JarvisError, PermissionDeniedError, etc.
    ├── tools/                                  # general utilities (package-root, not module-bound)
    │   ├── __init__.py
    │   ├── registry.py                         # tool name -> callable map + dispatcher
    │   ├── get_schema.py
    │   ├── get_doc.py
    │   ├── get_list.py
    │   └── run_report.py
    ├── tests/                                  # package-root tests
    │   ├── __init__.py
    │   ├── test_settings.py
    │   ├── test_exceptions.py
    │   ├── test_get_schema.py
    │   ├── test_get_doc.py
    │   ├── test_get_list.py
    │   ├── test_run_report.py
    │   ├── test_registry.py
    │   └── test_api.py
    └── jarvis/                                 # the "Jarvis" MODULE (per modules.txt)
        ├── __init__.py                         # empty marker
        └── doctype/
            └── jarvis_settings/
                ├── __init__.py
                ├── jarvis_settings.json        # Single DocType definition (module = "Jarvis")
                └── jarvis_settings.py          # Controller
```

**Why the `app/jarvis/jarvis/` nesting:** Frappe loads DocTypes via `<app>.<module_lowercased>.doctype.<doctype>.<controller>`. Our `modules.txt` lists `Jarvis`, so Frappe imports `jarvis.jarvis.doctype.jarvis_settings.jarvis_settings`. The inner `jarvis/` directory is the module's package — this matches ERPNext's pattern where modules like `Accounts` live at `apps/erpnext/erpnext/accounts/`. Only DocTypes (and other module-bound resources like Reports, Print Formats, Workflows) need to live under the module dir. General utilities (`tools/`, `api.py`, `exceptions.py`, `tests/`) live at the package root for cleaner imports.

Boundary notes:
- **Tools are pure functions** in their own files. One file = one tool. Easy to test, easy to grow the library.
- **Registry is the only place that knows the full tool list.** Adding a tool = adding a file and one registry entry.
- **`api.py` is thin** — only auth/whitelist + JSON-in/JSON-out + dispatch. No business logic.
- **`exceptions.py` is the shared error vocabulary.** Tools raise; `api.py` and the (future) socket layer translate to wire format.

---

### Task 1: App scaffolding

**Files:**
- Create: `app/pyproject.toml`
- Create: `app/README.md`
- Create: `app/license.txt`
- Create: `app/jarvis/__init__.py`
- Create: `app/jarvis/hooks.py`
- Create: `app/jarvis/modules.txt`
- Create: `app/jarvis/patches.txt`
- Create: `app/jarvis/jarvis/__init__.py` (empty — Jarvis module marker; required by Frappe's `<app>.<module>` import path)

- [ ] **Step 1: Write `pyproject.toml`**

Create `app/pyproject.toml`:

```toml
[project]
name = "jarvis"
authors = [{ name = "Aerele", email = "navin@aerele.in" }]
description = "AI superpowers for Frappe/ERPNext, powered by openclaw"
requires-python = ">=3.10"
readme = "README.md"
dynamic = ["version"]
dependencies = []

[build-system]
requires = ["flit_core >=3.4,<4"]
build-backend = "flit_core.buildapi"

[tool.flit.module]
name = "jarvis"
```

- [ ] **Step 2: Write `README.md` and `license.txt`**

`app/README.md`:
```markdown
# Jarvis

AI superpowers for Frappe/ERPNext, powered by openclaw.

See `docs/superpowers/specs/2026-05-15-jarvis-design.md` for the design.
```

`app/license.txt`:
```
MIT License
```

- [ ] **Step 3: Write `jarvis/__init__.py`**

```python
__version__ = "0.0.1"
```

- [ ] **Step 4: Write `hooks.py`**

```python
app_name = "jarvis"
app_title = "Jarvis"
app_publisher = "Aerele"
app_description = "AI superpowers for Frappe/ERPNext"
app_email = "navin@aerele.in"
app_license = "MIT"
```

- [ ] **Step 5: Write `modules.txt` and `patches.txt`**

`app/jarvis/modules.txt`:
```
Jarvis
```

`app/jarvis/patches.txt`: empty file (touch it).

Also create `app/jarvis/jarvis/__init__.py` as an empty file:
```bash
mkdir -p app/jarvis/jarvis && touch app/jarvis/jarvis/__init__.py
```
This is the package directory for the `Jarvis` module — Frappe's DocType import path requires it.

- [ ] **Step 6: Install the app on the test site**

Run from `/Users/venkatesh/bench/develop/jarvis/bench`:
```bash
bench --site jarvis.localhost install-app jarvis
```
Expected: command completes without error. `bench --site jarvis.localhost list-apps` shows `jarvis`.

- [ ] **Step 7: Commit**

```bash
cd /Users/venkatesh/bench/develop/jarvis
git add app/pyproject.toml app/README.md app/license.txt app/jarvis/__init__.py app/jarvis/hooks.py app/jarvis/modules.txt app/jarvis/patches.txt app/jarvis/jarvis/__init__.py
git commit -m "feat: scaffold jarvis frappe app"
```

---

### Task 2: `Jarvis Settings` single DocType

**Files:**
- Create: `app/jarvis/jarvis/doctype/jarvis_settings/__init__.py`
- Create: `app/jarvis/jarvis/doctype/jarvis_settings/jarvis_settings.json`
- Create: `app/jarvis/jarvis/doctype/jarvis_settings/jarvis_settings.py`
- Create: `app/jarvis/tests/__init__.py`
- Create: `app/jarvis/tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

`app/jarvis/tests/test_settings.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase


class TestJarvisSettings(FrappeTestCase):
    def test_settings_is_single(self):
        meta = frappe.get_meta("Jarvis Settings")
        self.assertTrue(meta.issingle, "Jarvis Settings must be a Single DocType")

    def test_settings_has_expected_fields(self):
        meta = frappe.get_meta("Jarvis Settings")
        fieldnames = {f.fieldname for f in meta.fields}
        for required in ("openclaw_api_key", "openclaw_endpoint", "token_budget_monthly"):
            self.assertIn(required, fieldnames, f"missing field: {required}")

    def test_api_key_is_password_field(self):
        meta = frappe.get_meta("Jarvis Settings")
        api_key_field = next(f for f in meta.fields if f.fieldname == "openclaw_api_key")
        self.assertEqual(api_key_field.fieldtype, "Password")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_settings
```
Expected: FAIL — "DocType Jarvis Settings not found" or similar.

- [ ] **Step 3: Write the DocType JSON**

`app/jarvis/jarvis/doctype/jarvis_settings/__init__.py`: empty file.

`app/jarvis/jarvis/doctype/jarvis_settings/jarvis_settings.json`:

```json
{
  "doctype": "DocType",
  "name": "Jarvis Settings",
  "module": "Jarvis",
  "issingle": 1,
  "custom": 0,
  "engine": "InnoDB",
  "field_order": [
    "openclaw_section",
    "openclaw_endpoint",
    "openclaw_api_key",
    "column_break_1",
    "token_budget_monthly",
    "enabled"
  ],
  "fields": [
    {
      "fieldname": "openclaw_section",
      "fieldtype": "Section Break",
      "label": "Openclaw Connection"
    },
    {
      "fieldname": "openclaw_endpoint",
      "fieldtype": "Data",
      "label": "Openclaw Endpoint",
      "description": "WebSocket URL of the openclaw cloud (e.g. wss://api.jarvis.example.com/agent)"
    },
    {
      "fieldname": "openclaw_api_key",
      "fieldtype": "Password",
      "label": "Openclaw API Key"
    },
    {
      "fieldname": "column_break_1",
      "fieldtype": "Column Break"
    },
    {
      "fieldname": "token_budget_monthly",
      "fieldtype": "Int",
      "label": "Monthly Token Budget",
      "default": "0",
      "description": "0 = unlimited. Otherwise hard cap before overage billing kicks in."
    },
    {
      "fieldname": "enabled",
      "fieldtype": "Check",
      "label": "Enabled",
      "default": "1"
    }
  ],
  "permissions": [
    {
      "role": "System Manager",
      "read": 1,
      "write": 1,
      "create": 1
    }
  ]
}
```

- [ ] **Step 4: Write the empty controller**

`app/jarvis/jarvis/doctype/jarvis_settings/jarvis_settings.py`:

```python
from frappe.model.document import Document


class JarvisSettings(Document):
    pass
```

- [ ] **Step 5: Migrate the site and re-run the test**

```bash
bench --site jarvis.localhost migrate
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_settings
```
Expected: PASS (all three tests).

- [ ] **Step 6: Commit**

```bash
git add app/jarvis/jarvis/doctype/jarvis_settings/ app/jarvis/tests/__init__.py app/jarvis/tests/test_settings.py
git commit -m "feat: add Jarvis Settings single DocType"
```

---

### Task 3: Exceptions module

**Files:**
- Create: `app/jarvis/exceptions.py`
- Create: `app/jarvis/tests/test_exceptions.py`

- [ ] **Step 1: Write the failing test**

`app/jarvis/tests/test_exceptions.py`:

```python
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import (
    JarvisError,
    ToolNotFoundError,
    PermissionDeniedError,
    InvalidArgumentError,
)


class TestExceptions(FrappeTestCase):
    def test_all_inherit_from_jarvis_error(self):
        for exc in (ToolNotFoundError, PermissionDeniedError, InvalidArgumentError):
            self.assertTrue(issubclass(exc, JarvisError))

    def test_carry_message(self):
        e = ToolNotFoundError("no such tool: foo")
        self.assertEqual(str(e), "no such tool: foo")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_exceptions
```
Expected: FAIL — `ModuleNotFoundError: No module named 'jarvis.exceptions'`.

- [ ] **Step 3: Write `exceptions.py`**

`app/jarvis/exceptions.py`:

```python
class JarvisError(Exception):
    """Base class for all Jarvis-raised errors."""


class ToolNotFoundError(JarvisError):
    """Raised when a tool name is not registered."""


class PermissionDeniedError(JarvisError):
    """Raised when the calling user lacks permission for the requested operation."""


class InvalidArgumentError(JarvisError):
    """Raised when tool arguments fail validation."""
```

- [ ] **Step 4: Run tests to verify pass**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_exceptions
```
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add app/jarvis/exceptions.py app/jarvis/tests/test_exceptions.py
git commit -m "feat: add Jarvis exception hierarchy"
```

---

### Task 4: `get_schema` tool

**Purpose:** Return a DocType's meta (field list with names, types, labels, options) so the agent knows the shape of a DocType before querying it. Read permission required on the DocType.

**Files:**
- Create: `app/jarvis/tools/__init__.py`
- Create: `app/jarvis/tools/get_schema.py`
- Create: `app/jarvis/tests/test_get_schema.py`

- [ ] **Step 1: Write the failing test**

`app/jarvis/tools/__init__.py`: empty file.

`app/jarvis/tests/test_get_schema.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.get_schema import get_schema


class TestGetSchema(FrappeTestCase):
    def test_returns_fields_for_known_doctype(self):
        result = get_schema(doctype="Customer")
        self.assertEqual(result["doctype"], "Customer")
        self.assertIn("fields", result)
        fieldnames = {f["fieldname"] for f in result["fields"]}
        self.assertIn("customer_name", fieldnames)

    def test_field_records_have_expected_keys(self):
        result = get_schema(doctype="Customer")
        f = result["fields"][0]
        for key in ("fieldname", "fieldtype", "label"):
            self.assertIn(key, f)

    def test_rejects_unknown_doctype(self):
        with self.assertRaises(InvalidArgumentError):
            get_schema(doctype="Definitely Not A DocType")

    def test_rejects_missing_argument(self):
        with self.assertRaises(InvalidArgumentError):
            get_schema(doctype="")

    def test_permission_check_blocks_unauthorized_user(self):
        # Create a user with no roles and switch to them.
        user_email = "schemaless@example.com"
        if not frappe.db.exists("User", user_email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": user_email,
                "first_name": "Schemaless",
                "send_welcome_email": 0,
            })
            user.insert(ignore_permissions=True)
        frappe.set_user(user_email)
        try:
            with self.assertRaises(PermissionDeniedError):
                get_schema(doctype="Customer")
        finally:
            frappe.set_user("Administrator")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_get_schema
```
Expected: FAIL — `ModuleNotFoundError: No module named 'jarvis.tools.get_schema'`.

- [ ] **Step 3: Implement `get_schema`**

`app/jarvis/tools/get_schema.py`:

```python
import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError


def get_schema(doctype: str) -> dict:
    """Return meta for a DocType: name and field list.

    Enforces read permission on the DocType for the current user.
    """
    if not doctype:
        raise InvalidArgumentError("doctype is required")

    if not frappe.db.exists("DocType", doctype):
        raise InvalidArgumentError(f"unknown DocType: {doctype}")

    if not frappe.has_permission(doctype, ptype="read"):
        raise PermissionDeniedError(f"no read permission on {doctype}")

    meta = frappe.get_meta(doctype)
    fields = [
        {
            "fieldname": f.fieldname,
            "fieldtype": f.fieldtype,
            "label": f.label,
            "options": f.options,
            "reqd": bool(f.reqd),
        }
        for f in meta.fields
    ]
    return {"doctype": doctype, "fields": fields}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_get_schema
```
Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add app/jarvis/tools/__init__.py app/jarvis/tools/get_schema.py app/jarvis/tests/test_get_schema.py
git commit -m "feat: add get_schema tool"
```

---

### Task 5: `get_doc` tool

**Purpose:** Return a single document by DocType and name. Read permission required on the document (Frappe enforces both DocType-level and record-level permissions via `has_permission`).

**Files:**
- Create: `app/jarvis/tools/get_doc.py`
- Create: `app/jarvis/tests/test_get_doc.py`

- [ ] **Step 1: Write the failing test**

`app/jarvis/tests/test_get_doc.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.get_doc import get_doc


class TestGetDoc(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not frappe.db.exists("Customer", "Jarvis Test Customer"):
            frappe.get_doc({
                "doctype": "Customer",
                "customer_name": "Jarvis Test Customer",
                "customer_type": "Company",
                "customer_group": "All Customer Groups",
                "territory": "All Territories",
            }).insert(ignore_permissions=True)

    def test_returns_doc_by_name(self):
        result = get_doc(doctype="Customer", name="Jarvis Test Customer")
        self.assertEqual(result["name"], "Jarvis Test Customer")
        self.assertEqual(result["customer_name"], "Jarvis Test Customer")

    def test_rejects_missing_doctype(self):
        with self.assertRaises(InvalidArgumentError):
            get_doc(doctype="", name="Jarvis Test Customer")

    def test_rejects_missing_name(self):
        with self.assertRaises(InvalidArgumentError):
            get_doc(doctype="Customer", name="")

    def test_rejects_unknown_doc(self):
        with self.assertRaises(InvalidArgumentError):
            get_doc(doctype="Customer", name="Definitely Not A Customer")

    def test_permission_check_blocks_unauthorized_user(self):
        user_email = "docless@example.com"
        if not frappe.db.exists("User", user_email):
            frappe.get_doc({
                "doctype": "User",
                "email": user_email,
                "first_name": "Docless",
                "send_welcome_email": 0,
            }).insert(ignore_permissions=True)
        frappe.set_user(user_email)
        try:
            with self.assertRaises(PermissionDeniedError):
                get_doc(doctype="Customer", name="Jarvis Test Customer")
        finally:
            frappe.set_user("Administrator")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_get_doc
```
Expected: FAIL — `ModuleNotFoundError: No module named 'jarvis.tools.get_doc'`.

- [ ] **Step 3: Implement `get_doc`**

`app/jarvis/tools/get_doc.py`:

```python
import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError


def get_doc(doctype: str, name: str) -> dict:
    """Return a single document as a dict.

    Enforces read permission on the specific document for the current user.
    """
    if not doctype:
        raise InvalidArgumentError("doctype is required")
    if not name:
        raise InvalidArgumentError("name is required")

    if not frappe.db.exists(doctype, name):
        raise InvalidArgumentError(f"unknown {doctype}: {name}")

    if not frappe.has_permission(doctype, ptype="read", doc=name):
        raise PermissionDeniedError(f"no read permission on {doctype} {name}")

    doc = frappe.get_doc(doctype, name)
    return doc.as_dict(no_default_fields=False)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_get_doc
```
Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add app/jarvis/tools/get_doc.py app/jarvis/tests/test_get_doc.py
git commit -m "feat: add get_doc tool"
```

---

### Task 6: `get_list` tool

**Purpose:** Filtered list of documents. Frappe's `get_list` already applies the user's permissions (it filters out records they cannot see). Tool enforces DocType read permission up front and caps `limit` to 1000 to prevent runaway agent queries.

**Files:**
- Create: `app/jarvis/tools/get_list.py`
- Create: `app/jarvis/tests/test_get_list.py`

- [ ] **Step 1: Write the failing test**

`app/jarvis/tests/test_get_list.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.get_list import get_list


class TestGetList(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for name in ("Jarvis List A", "Jarvis List B"):
            if not frappe.db.exists("Customer", name):
                frappe.get_doc({
                    "doctype": "Customer",
                    "customer_name": name,
                    "customer_type": "Company",
                    "customer_group": "All Customer Groups",
                    "territory": "All Territories",
                }).insert(ignore_permissions=True)

    def test_returns_rows(self):
        rows = get_list(
            doctype="Customer",
            fields=["name", "customer_name"],
            filters={"customer_name": ["like", "Jarvis List%"]},
        )
        names = {r["name"] for r in rows}
        self.assertEqual(names, {"Jarvis List A", "Jarvis List B"})

    def test_respects_limit(self):
        rows = get_list(
            doctype="Customer",
            fields=["name"],
            filters={"customer_name": ["like", "Jarvis List%"]},
            limit=1,
        )
        self.assertEqual(len(rows), 1)

    def test_rejects_excessive_limit(self):
        with self.assertRaises(InvalidArgumentError):
            get_list(doctype="Customer", fields=["name"], limit=5000)

    def test_rejects_missing_doctype(self):
        with self.assertRaises(InvalidArgumentError):
            get_list(doctype="", fields=["name"])

    def test_permission_check_blocks_unauthorized_user(self):
        user_email = "listless@example.com"
        if not frappe.db.exists("User", user_email):
            frappe.get_doc({
                "doctype": "User",
                "email": user_email,
                "first_name": "Listless",
                "send_welcome_email": 0,
            }).insert(ignore_permissions=True)
        frappe.set_user(user_email)
        try:
            with self.assertRaises(PermissionDeniedError):
                get_list(doctype="Customer", fields=["name"])
        finally:
            frappe.set_user("Administrator")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_get_list
```
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `get_list`**

`app/jarvis/tools/get_list.py`:

```python
import frappe

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError

MAX_LIMIT = 1000


def get_list(
    doctype: str,
    fields: list[str] | None = None,
    filters: dict | list | None = None,
    order_by: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """List documents with filters.

    Frappe's get_list applies per-user record permissions automatically.
    We additionally enforce DocType-level read permission and cap the limit.
    """
    if not doctype:
        raise InvalidArgumentError("doctype is required")
    if limit <= 0 or limit > MAX_LIMIT:
        raise InvalidArgumentError(f"limit must be between 1 and {MAX_LIMIT}")

    if not frappe.has_permission(doctype, ptype="read"):
        raise PermissionDeniedError(f"no read permission on {doctype}")

    return frappe.get_list(
        doctype,
        fields=fields or ["name"],
        filters=filters or {},
        order_by=order_by,
        limit=limit,
    )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_get_list
```
Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add app/jarvis/tools/get_list.py app/jarvis/tests/test_get_list.py
git commit -m "feat: add get_list tool"
```

---

### Task 7: `run_report` tool

**Purpose:** Execute a saved ERPNext Report Builder / Query / Script report by name. Frappe ships `frappe.desk.query_report.run`, which already enforces report-level permissions. Tool wraps it and surfaces a clean result.

**Files:**
- Create: `app/jarvis/tools/run_report.py`
- Create: `app/jarvis/tests/test_run_report.py`

- [ ] **Step 1: Write the failing test**

`app/jarvis/tests/test_run_report.py`:

```python
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.run_report import run_report


class TestRunReport(FrappeTestCase):
    def test_runs_known_report(self):
        company = frappe.defaults.get_global_default("company")
        if not company:
            self.skipTest("test bench has no default company; happy-path covered in E2E task")
        result = run_report(
            report_name="Sales Register",
            filters={"from_date": "2020-01-01", "to_date": "2020-01-02", "company": company},
        )
        self.assertIn("columns", result)
        self.assertIn("result", result)

    def test_rejects_unknown_report(self):
        with self.assertRaises(InvalidArgumentError):
            run_report(report_name="Definitely Not A Report")

    def test_rejects_missing_report_name(self):
        with self.assertRaises(InvalidArgumentError):
            run_report(report_name="")

    def test_permission_check_blocks_unauthorized_user(self):
        user_email = "reportless@example.com"
        if not frappe.db.exists("User", user_email):
            frappe.get_doc({
                "doctype": "User",
                "email": user_email,
                "first_name": "Reportless",
                "send_welcome_email": 0,
            }).insert(ignore_permissions=True)
        frappe.set_user(user_email)
        try:
            with self.assertRaises(PermissionDeniedError):
                run_report(report_name="Sales Register")
        finally:
            frappe.set_user("Administrator")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_run_report
```
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `run_report`**

`app/jarvis/tools/run_report.py`:

```python
import frappe
from frappe.desk.query_report import run as frappe_run_report

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError


def run_report(report_name: str, filters: dict | None = None) -> dict:
    """Execute a saved Frappe Report by name.

    Frappe enforces report-level permissions internally and raises frappe.PermissionError
    on denial; we translate that to PermissionDeniedError so all tools share one
    exception contract. Returns a dict with `columns` and `result` keys.
    """
    if not report_name:
        raise InvalidArgumentError("report_name is required")

    if not frappe.db.exists("Report", report_name):
        raise InvalidArgumentError(f"unknown Report: {report_name}")

    try:
        return frappe_run_report(report_name=report_name, filters=filters or {})
    except frappe.PermissionError as e:
        raise PermissionDeniedError(str(e) or f"no permission to run report {report_name}") from e
```

- [ ] **Step 4: Run tests to verify pass**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_run_report
```
Expected: PASS (all three tests).

Note: If the test bench does not have any Sales Invoice records for the date range, `run_report` will still return a valid `{columns, result}` dict — `result` may simply be empty. That's fine; the test asserts structure, not row count.

- [ ] **Step 5: Commit**

```bash
git add app/jarvis/tools/run_report.py app/jarvis/tests/test_run_report.py
git commit -m "feat: add run_report tool"
```

---

### Task 8: Tool registry + dispatcher

**Purpose:** A single place that knows every tool. The (future) socket layer and the (current) HTTP API will both go through this.

**Files:**
- Create: `app/jarvis/tools/registry.py`
- Create: `app/jarvis/tests/test_registry.py`

- [ ] **Step 1: Write the failing test**

`app/jarvis/tests/test_registry.py`:

```python
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import ToolNotFoundError, InvalidArgumentError
from jarvis.tools.registry import dispatch, list_tools


class TestRegistry(FrappeTestCase):
    def test_list_tools_contains_all_four(self):
        names = set(list_tools())
        self.assertEqual(names, {"get_schema", "get_doc", "get_list", "run_report"})

    def test_dispatch_invokes_correct_tool(self):
        result = dispatch("get_schema", {"doctype": "Customer"})
        self.assertEqual(result["doctype"], "Customer")

    def test_dispatch_unknown_tool_raises(self):
        with self.assertRaises(ToolNotFoundError):
            dispatch("not_a_tool", {})

    def test_dispatch_rejects_non_dict_args(self):
        with self.assertRaises(InvalidArgumentError):
            dispatch("get_schema", "not a dict")

    def test_dispatch_passes_args_through(self):
        # Missing required arg should bubble up the tool's own InvalidArgumentError.
        with self.assertRaises(InvalidArgumentError):
            dispatch("get_doc", {"doctype": "Customer"})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_registry
```
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the registry**

`app/jarvis/tools/registry.py`:

```python
from typing import Callable

from jarvis.exceptions import InvalidArgumentError, ToolNotFoundError
from jarvis.tools.get_doc import get_doc
from jarvis.tools.get_list import get_list
from jarvis.tools.get_schema import get_schema
from jarvis.tools.run_report import run_report

_TOOLS: dict[str, Callable] = {
    "get_schema": get_schema,
    "get_doc": get_doc,
    "get_list": get_list,
    "run_report": run_report,
}


def list_tools() -> list[str]:
    return sorted(_TOOLS.keys())


def dispatch(tool_name: str, args: dict):
    if tool_name not in _TOOLS:
        raise ToolNotFoundError(f"no such tool: {tool_name}")
    if not isinstance(args, dict):
        raise InvalidArgumentError("args must be a dict")
    return _TOOLS[tool_name](**args)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_registry
```
Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add app/jarvis/tools/registry.py app/jarvis/tests/test_registry.py
git commit -m "feat: add tool registry and dispatcher"
```

---

### Task 9: Whitelisted HTTP API endpoint

**Purpose:** Expose the dispatcher over Frappe's HTTP layer for smoke-testing before the socket transport (Plan 2) exists. This is a temporary developer-facing entry point; the socket gateway will replace it as the production path, but the endpoint stays available for ops/debug.

**Files:**
- Create: `app/jarvis/api.py`
- Create: `app/jarvis/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

`app/jarvis/tests/test_api.py`:

```python
import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.api import call_tool


class TestCallTool(FrappeTestCase):
    def test_calls_tool_and_returns_result(self):
        result = call_tool(tool="get_schema", args={"doctype": "Customer"})
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["data"]["doctype"], "Customer")

    def test_accepts_json_string_args(self):
        # HTTP clients often send the args as a JSON string.
        result = call_tool(tool="get_schema", args='{"doctype": "Customer"}')
        self.assertEqual(result["ok"], True)

    def test_unknown_tool_returns_error_envelope(self):
        result = call_tool(tool="not_a_tool", args={})
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["error"]["code"], "ToolNotFoundError")

    def test_invalid_args_returns_error_envelope(self):
        result = call_tool(tool="get_doc", args={"doctype": "Customer"})
        self.assertEqual(result["ok"], False)
        self.assertEqual(result["error"]["code"], "InvalidArgumentError")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_api
```
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the endpoint**

`app/jarvis/api.py`:

```python
import json

import frappe

from jarvis.exceptions import JarvisError
from jarvis.tools.registry import dispatch


@frappe.whitelist()
def call_tool(tool: str, args: dict | str | None = None) -> dict:
    """Whitelisted entry point for tool dispatch.

    Returns a {ok, data} envelope on success or {ok: False, error: {code, message}} on failure.
    The calling user is whoever Frappe's session resolves to; that user's permissions are
    what the tool sees.
    """
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError as e:
            return _error("InvalidArgumentError", f"args is not valid JSON: {e}")
    args = args or {}

    try:
        data = dispatch(tool, args)
    except JarvisError as e:
        return _error(type(e).__name__, str(e))
    except frappe.PermissionError as e:
        return _error("PermissionDeniedError", str(e) or "permission denied")

    return {"ok": True, "data": data}


def _error(code: str, message: str) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
bench --site jarvis.localhost run-tests --app jarvis --module jarvis.tests.test_api
```
Expected: PASS (all four tests).

- [ ] **Step 5: Commit**

```bash
git add app/jarvis/api.py app/jarvis/tests/test_api.py
git commit -m "feat: add whitelisted call_tool endpoint"
```

---

### Task 10: End-to-end smoke test on the bench

**Purpose:** Verify the whole foundation works from outside Python — via the HTTP API as a real client would call it.

- [ ] **Step 1: Start the bench**

```bash
cd /Users/venkatesh/bench/develop/jarvis/bench
bench start
```
Expected: bench runs, no errors related to jarvis on startup.

- [ ] **Step 2: Run the full app test suite**

In another terminal:
```bash
cd /Users/venkatesh/bench/develop/jarvis/bench
bench --site jarvis.localhost run-tests --app jarvis
```
Expected: all tests from Tasks 2–9 PASS.

- [ ] **Step 3: Call `call_tool` over HTTP as Administrator**

Use `bench --site jarvis.localhost execute` to grab an API key/secret for Administrator, or generate one in the user profile UI. Then:

```bash
curl -X POST "http://jarvis.localhost:8000/api/method/jarvis.api.call_tool" \
  -H "Authorization: token <api_key>:<api_secret>" \
  -H "Content-Type: application/json" \
  -d '{"tool": "get_schema", "args": {"doctype": "Customer"}}'
```
Expected response: `{"message": {"ok": true, "data": {"doctype": "Customer", "fields": [...]}}}`.

- [ ] **Step 4: Call `call_tool` as a low-permission user**

Create a user with the `Employee Self Service` role only. Generate API key/secret for that user. Repeat the curl above with that user's credentials, calling `get_doc` on a Sales Invoice.

Expected response: `{"message": {"ok": false, "error": {"code": "PermissionDeniedError", "message": "..."}}}`.

- [ ] **Step 5: Verify Jarvis Settings is editable in Desk**

In the browser, open `/app/jarvis-settings`. The Single DocType form should render with the four fields defined in Task 2.

- [ ] **Step 6: Tag the foundation milestone**

```bash
cd /Users/venkatesh/bench/develop/jarvis
git tag -a foundation-v0.0.1 -m "Customer-side foundation: app, settings, MCP tools, HTTP API"
```

---

## Verification Summary

After completing all tasks above, the following should be true:

- `bench --site <site> list-apps` shows `jarvis`.
- `bench --site <site> run-tests --app jarvis` passes with all tests green (six test modules, ~25 tests).
- `/app/jarvis-settings` opens in Desk with all four fields.
- `POST /api/method/jarvis.api.call_tool` works for all four tools as Administrator.
- The same endpoint correctly returns a `PermissionDeniedError` envelope when called as a user without the required permission.
- All work is committed; a `foundation-v0.0.1` tag exists.

## What This Plan Does NOT Do

These belong to later plans:
- Cloud-side openclaw runtime (Plan 2).
- Outbound socket client + protocol (Plan 2/3).
- Chat UI in Desk (Plan 4).
- Tables, charts, saved views rendering (Plan 5).
- DocType skill library on the openclaw side (Plan 6).
- Token usage metering (Plan 7).
- Pricing/billing tiers (deferred from spec).

## Open Questions to Resolve Before Plan 2

- Exact Frappe v15 minor version on the development bench (affects test-runner invocation).
- Whether the openclaw runtime will be a hosted service we control or a self-hosted component during early development (affects how the socket gateway is reachable in dev).
- Which LLM provider(s) openclaw will call out to in dev (affects whether dev work needs cloud credentials).
