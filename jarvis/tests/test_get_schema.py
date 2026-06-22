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

    def test_default_returns_five_keys_per_field(self):
        """The default per-field shape carries fieldname / fieldtype /
        label / options / reqd. options and reqd are load-bearing:
        Link/Select/Table targets and write-path requireds. The
        previous 3-key slim default was too aggressive and got walked
        back."""
        result = get_schema(doctype="Customer")
        f = result["fields"][0]
        self.assertEqual(
            set(f.keys()),
            {"fieldname", "fieldtype", "label", "options", "reqd"},
        )

    def test_default_includes_options_on_link_field(self):
        """A Link field's options carries its target DocType. Without
        this the agent can't follow the link."""
        result = get_schema(doctype="Sales Invoice")
        customer_field = next(f for f in result["fields"] if f["fieldname"] == "customer")
        self.assertEqual(customer_field["fieldtype"], "Link")
        self.assertEqual(customer_field["options"], "Customer")

    def test_default_includes_options_on_table_field_but_no_child_fields(self):
        """A Table field's options names the child DocType. The agent
        uses that to call get_schema on the child when it needs the
        child fields - the recursive child_fields expansion is what we
        cut to keep transcripts small."""
        result = get_schema(doctype="Sales Invoice")
        items_field = next(f for f in result["fields"] if f["fieldname"] == "items")
        self.assertEqual(items_field["fieldtype"], "Table")
        self.assertEqual(items_field["options"], "Sales Invoice Item")
        self.assertNotIn("child_fields", items_field)

    def test_default_includes_reqd(self):
        """reqd is a single bool per field - cheap, but essential for
        the agent to know which fields must be set on create_doc."""
        result = get_schema(doctype="Customer")
        # customer_name is mandatory on Customer (the doc's autoname);
        # at least one field on every standard DocType has reqd=True.
        reqds = [f["reqd"] for f in result["fields"]]
        self.assertIn(True, reqds, "expected at least one reqd=True field")

    def test_verbose_expands_child_table_schemas(self):
        """verbose=True is the opt-in for inlined child schemas. Same
        per-field shape (5 keys) inside the expansion."""
        result = get_schema(doctype="Sales Invoice", verbose=True)
        items_field = next(f for f in result["fields"] if f["fieldname"] == "items")
        self.assertEqual(items_field["fieldtype"], "Table")
        self.assertEqual(items_field["options"], "Sales Invoice Item")
        self.assertIn("child_fields", items_field)
        child_fieldnames = {cf["fieldname"] for cf in items_field["child_fields"]}
        self.assertIn("item_code", child_fieldnames)
        self.assertIn("qty", child_fieldnames)
        # Child records use the same 5-key shape.
        first_child = items_field["child_fields"][0]
        self.assertEqual(
            set(first_child.keys()),
            {"fieldname", "fieldtype", "label", "options", "reqd"},
        )

    def test_verbose_non_table_fields_have_no_child_fields_key(self):
        result = get_schema(doctype="Customer", verbose=True)
        customer_name = next(f for f in result["fields"] if f["fieldname"] == "customer_name")
        self.assertNotIn("child_fields", customer_name)

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
