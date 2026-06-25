import frappe
from frappe.tests.utils import FrappeTestCase

class TestJarvisLLMPool(FrappeTestCase):
    def test_pool_doctype_exists_and_is_single_sysmanager_only(self):
        assert frappe.db.exists("DocType", "Jarvis LLM Pool")
        meta = frappe.get_meta("Jarvis LLM Pool")
        assert meta.issingle == 1
        # System Manager is the only role with write
        perms = [p for p in frappe.get_all("DocPerm", filters={"parent": "Jarvis LLM Pool", "write": 1}, fields=["role"])]
        roles = {p["role"] for p in perms}
        assert roles == {"System Manager"}, roles

    def test_pool_model_child_fields(self):
        meta = frappe.get_meta("Jarvis LLM Pool Model")
        fields = {f.fieldname: f.fieldtype for f in meta.fields}
        for fn, ft in {"provider":"Data","model":"Data","tier":"Select","base_url":"Data",
                       "credential_type":"Select","api_key":"Password","order":"Int","enabled":"Check"}.items():
            assert fields.get(fn) == ft, (fn, fields.get(fn))

    def test_subscription_grandchild_fields(self):
        meta = frappe.get_meta("Jarvis LLM Pool Subscription Account")
        fields = {f.fieldname: f.fieldtype for f in meta.fields}
        for fn, ft in {"upstream":"Select","account_ref":"Data","label":"Data",
                       "oauth_blob":"Password","rotation":"Select"}.items():
            assert fields.get(fn) == ft, (fn, fields.get(fn))
