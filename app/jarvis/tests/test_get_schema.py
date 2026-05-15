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
