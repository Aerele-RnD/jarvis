from frappe.tests.utils import FrappeTestCase

from jarvis.exceptions import ToolNotFoundError, InvalidArgumentError
from jarvis.tools.registry import dispatch, list_tools


class TestRegistry(FrappeTestCase):
    def test_list_tools_contains_all_registered(self):
        names = set(list_tools())
        self.assertEqual(
            names,
            {
                "get_schema",
                "get_doc",
                "get_list",
                "run_report",
                "run_query",
                "update_doc",
                "create_doc",
                "submit_doc",
            },
        )

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
