import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import InvalidArgumentError, PermissionDeniedError
from jarvis.tools.get_creation_context import get_creation_context


def _todo(description, **kw):
    return frappe.get_doc({
        "doctype": "ToDo",
        "description": description,
        **kw,
    }).insert(ignore_permissions=True)


class TestGetCreationContext(FrappeTestCase):
    """ToDo is a core doctype (no ERPNext needed) with Select classifier fields
    (priority/status), so it exercises the field map, context matching, facets,
    and fallbacks without heavy fixtures."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for i in range(3):
            _todo(f"jarvis-ctx high {i}", priority="High", status="Open")
        for i in range(2):
            _todo(f"jarvis-ctx low {i}", priority="Low", status="Open")

    def test_returns_expected_shape(self):
        ctx = get_creation_context("ToDo")
        for key in ("doctype", "fields", "mandatory", "similar", "example",
                    "match_note", "facets", "note"):
            self.assertIn(key, ctx)
        self.assertEqual(ctx["doctype"], "ToDo")
        self.assertTrue(ctx["fields"])
        for f in ctx["fields"]:
            self.assertLessEqual(
                {"fieldname", "fieldtype", "mandatory", "auto", "readonly"},
                set(f.keys()),
            )

    def test_mandatory_matches_meta(self):
        ctx = get_creation_context("ToDo")
        expected = {df.fieldname for df in frappe.get_meta("ToDo").fields if df.reqd}
        self.assertEqual(set(ctx["mandatory"]), expected)
        # every listed mandatory field is flagged mandatory in the field map
        flagged = {f["fieldname"] for f in ctx["fields"] if f["mandatory"]}
        self.assertEqual(flagged, set(ctx["mandatory"]))

    def test_context_match_on_select(self):
        ctx = get_creation_context("ToDo", {"priority": "High"}, limit=10)
        self.assertTrue(ctx["similar"])
        self.assertTrue(all(r.get("priority") == "High" for r in ctx["similar"]))
        self.assertIn("priority=High", ctx["match_note"])
        self.assertFalse(ctx["facets"])  # facets surface only when no hint resolved

    def test_recent_fallback_when_no_match(self):
        ctx = get_creation_context("ToDo", {"priority": "__no_such_value__"})
        self.assertEqual(ctx["match_note"], "recent - no context matched")
        self.assertTrue(ctx["similar"])  # ToDos exist from setUpClass

    def test_facets_when_no_context(self):
        ctx = get_creation_context("ToDo")
        self.assertTrue(ctx["facets"])  # priority/status are Select classifiers
        joined = {v for vals in ctx["facets"].values() for v in vals}
        self.assertIn("High", joined)

    def test_example_is_full_doc(self):
        ctx = get_creation_context("ToDo", {"priority": "High"})
        self.assertIsNotNone(ctx["example"])
        self.assertIsInstance(ctx["example"], dict)
        # no_default_fields strips owner/creation/name/doctype (lean payload);
        # real data fields stay.
        self.assertEqual(ctx["example"].get("priority"), "High")
        self.assertIn("description", ctx["example"])

    def test_partial_relaxation_keeps_matching_hint(self):
        """Two hints whose combination matches nothing: the weakest is dropped
        and the note is flagged (relaxed)."""
        ctx = get_creation_context("ToDo", {"priority": "High", "status": "__no_such__"})
        self.assertIn("(relaxed)", ctx["match_note"])
        self.assertIn("priority=High", ctx["match_note"])
        self.assertTrue(all(r.get("priority") == "High" for r in ctx["similar"]))

    def test_json_string_context_is_parsed(self):
        ctx = get_creation_context("ToDo", '{"priority": "High"}')
        self.assertIn("priority=High", ctx["match_note"])

    def test_non_json_string_context_rejected(self):
        with self.assertRaises(InvalidArgumentError):
            get_creation_context("ToDo", "Furniture")

    def test_single_doctype_rejected(self):
        with self.assertRaises(InvalidArgumentError):
            get_creation_context("System Settings")

    def test_istable_rejected(self):
        with self.assertRaises(InvalidArgumentError):
            get_creation_context("Contact Email")

    def test_unknown_doctype_rejected(self):
        with self.assertRaises(InvalidArgumentError):
            get_creation_context("No Such Doctype 123")

    def test_loose_hint_resolves_to_link_field(self):
        """A context key that isn't a fieldname resolves to the Link field whose
        target holds the value (generic party discovery). Tested on the helper
        so it's independent of which of ToDo's two User-links wins."""
        from jarvis.tools.get_creation_context import _resolve_link_field

        meta = frappe.get_meta("ToDo")
        resolved = _resolve_link_field(meta, "Administrator")  # a User
        self.assertIsNotNone(resolved)
        df = {d.fieldname: d for d in meta.fields}[resolved]
        self.assertEqual(df.fieldtype, "Link")
        self.assertEqual(df.options, "User")

    def test_permission_denied_without_create(self):
        user_email = "ctxless@example.com"
        if not frappe.db.exists("User", user_email):
            frappe.get_doc({
                "doctype": "User", "email": user_email, "first_name": "Ctxless",
                "send_welcome_email": 0,
            }).insert(ignore_permissions=True)
        frappe.set_user(user_email)
        try:
            with self.assertRaises(PermissionDeniedError):
                get_creation_context("User")
        finally:
            frappe.set_user("Administrator")
