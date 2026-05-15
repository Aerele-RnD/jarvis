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
