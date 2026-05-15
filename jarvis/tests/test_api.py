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
