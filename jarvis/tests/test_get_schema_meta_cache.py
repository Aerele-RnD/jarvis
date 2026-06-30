"""Tests for the get_schema additions: doctype-level metadata
(is_submittable / autoname / workflow) and the Redis TTL cache + refresh."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.tools import get_schema as gs


class TestGetSchemaMetaCache(FrappeTestCase):
    def setUp(self):
        for k in ("jarvis_schema:ToDo:0", "jarvis_schema:Journal Entry:0"):
            frappe.cache().delete_value(k)

    def test_includes_doctype_metadata_keys(self):
        s = gs.get_schema("ToDo")
        for k in ("doctype", "is_submittable", "autoname", "naming_rule",
                  "workflow", "fields"):
            self.assertIn(k, s)
        self.assertIsInstance(s["fields"], list)

    def test_submittable_flag(self):
        self.assertTrue(gs.get_schema("Journal Entry")["is_submittable"])
        self.assertFalse(gs.get_schema("ToDo")["is_submittable"])

    def test_result_is_cached(self):
        gs.get_schema("ToDo")
        self.assertIsNotNone(frappe.cache().get_value("jarvis_schema:ToDo:0"))

    def test_cache_hit_skips_rebuild_and_refresh_busts(self):
        gs.get_schema("ToDo")  # primes the cache
        with patch("jarvis.tools.get_schema._build_schema",
                   wraps=gs._build_schema) as build:
            gs.get_schema("ToDo")                 # cache hit -> no rebuild
            self.assertEqual(build.call_count, 0)
            gs.get_schema("ToDo", refresh=True)   # refresh -> rebuild
            self.assertEqual(build.call_count, 1)

    def test_stringified_false_is_treated_as_slim(self):
        for k in ("jarvis_schema:ToDo:0", "jarvis_schema:ToDo:1"):
            frappe.cache().delete_value(k)
        gs.get_schema("ToDo", verbose="false")  # truthy string must NOT enable verbose
        self.assertIsNotNone(frappe.cache().get_value("jarvis_schema:ToDo:0"))
        self.assertIsNone(frappe.cache().get_value("jarvis_schema:ToDo:1"))

    def test_refresh_busts_both_variants(self):
        gs.get_schema("ToDo", verbose=False)  # caches :0
        gs.get_schema("ToDo", verbose=True)   # caches :1
        self.assertIsNotNone(frappe.cache().get_value("jarvis_schema:ToDo:1"))
        gs.get_schema("ToDo", refresh=True)   # slim refresh must still bust :1
        self.assertIsNone(frappe.cache().get_value("jarvis_schema:ToDo:1"))
