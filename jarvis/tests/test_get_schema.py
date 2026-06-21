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

    def test_slim_default_returns_three_keys_per_field(self):
        """The slim default keeps transcripts small. Each field record
        carries fieldname / fieldtype / label and nothing else."""
        result = get_schema(doctype="Customer")
        f = result["fields"][0]
        self.assertEqual(set(f.keys()), {"fieldname", "fieldtype", "label"})

    def test_slim_default_does_not_expand_child_tables(self):
        """In the slim shape, Table fields surface as ordinary records
        with no child_fields recursion. Agent fetches the child DocType
        explicitly if it needs to (cheap follow-up call vs. always
        carrying the nested blob)."""
        result = get_schema(doctype="Sales Invoice")
        items_field = next(f for f in result["fields"] if f["fieldname"] == "items")
        self.assertEqual(items_field["fieldtype"], "Table")
        self.assertNotIn("child_fields", items_field)
        # options is not in the slim shape either, so the agent has to
        # call get_schema again on "Sales Invoice Item" or pass verbose.
        self.assertNotIn("options", items_field)

    def test_verbose_returns_all_five_keys_per_field(self):
        """verbose=True restores the pre-slim shape: fieldname /
        fieldtype / label / options / reqd."""
        result = get_schema(doctype="Customer", verbose=True)
        f = result["fields"][0]
        for key in ("fieldname", "fieldtype", "label", "options", "reqd"):
            self.assertIn(key, f)

    def test_verbose_expands_child_table_schemas(self):
        """verbose=True restores the inlined child schema for Table /
        Table MultiSelect fields. Same shape as before the slim default
        landed."""
        result = get_schema(doctype="Sales Invoice", verbose=True)
        items_field = next(f for f in result["fields"] if f["fieldname"] == "items")
        self.assertEqual(items_field["fieldtype"], "Table")
        self.assertEqual(items_field["options"], "Sales Invoice Item")
        self.assertIn("child_fields", items_field)
        child_fieldnames = {cf["fieldname"] for cf in items_field["child_fields"]}
        self.assertIn("item_code", child_fieldnames)
        self.assertIn("qty", child_fieldnames)

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
