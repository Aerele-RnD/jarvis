"""Unit tests for jarvis.tools.summarize_dataset (pure-Python, no DB)."""

import math
import unittest

from jarvis.exceptions import InvalidArgumentError
from jarvis.tools.summarize_dataset import summarize_dataset


class TestSummarizeDataset(unittest.TestCase):
	def test_dict_rows_numeric_and_categorical(self):
		rows = [
			{"region": "N", "amt": 10},
			{"region": "S", "amt": 20},
			{"region": "N", "amt": "30"},  # numeric-looking string coerces
			{"region": "S", "amt": None},  # null dropped
		]
		out = summarize_dataset(rows)
		self.assertEqual(out["row_count"], 4)
		amt = out["columns"]["amt"]
		self.assertEqual(amt["type"], "numeric")
		self.assertEqual(amt["count"], 3)
		self.assertEqual(amt["null_count"], 1)
		self.assertEqual(amt["sum"], 60.0)
		self.assertEqual(amt["mean"], 20.0)
		self.assertEqual(amt["min"], 10)
		self.assertEqual(amt["max"], 30.0)
		region = out["columns"]["region"]
		self.assertEqual(region["type"], "categorical")
		self.assertEqual(region["distinct"], 2)
		self.assertEqual(region["top"][0]["count"], 2)

	def test_list_of_lists_needs_columns(self):
		with self.assertRaises(InvalidArgumentError):
			summarize_dataset([[1, 2], [3, 4]])
		out = summarize_dataset([[1, "a"], [2, "b"], [3, "a"]], columns=["n", "g"])
		self.assertEqual(out["columns"]["n"]["type"], "numeric")
		self.assertEqual(out["columns"]["g"]["type"], "categorical")
		self.assertEqual(out["columns"]["g"]["distinct"], 2)

	def test_mixed_column_is_mixed(self):
		out = summarize_dataset([{"x": 1}, {"x": "abc"}, {"x": 2}])
		self.assertEqual(out["columns"]["x"]["type"], "mixed")
		self.assertIn("top", out["columns"]["x"])

	def test_empty_raises(self):
		with self.assertRaises(InvalidArgumentError):
			summarize_dataset([])

	def test_top_n_capped(self):
		rows = [{"k": f"cat{i % 7}"} for i in range(50)]  # non-numeric -> categorical
		out = summarize_dataset(rows, top_n=3)
		self.assertEqual(out["columns"]["k"]["type"], "categorical")
		self.assertEqual(len(out["columns"]["k"]["top"]), 3)

	def test_nan_inf_strings_do_not_poison_numeric(self):
		# 'nan'/'inf' must NOT coerce to float and turn the column numeric with
		# NaN/inf stats; they are non-numeric tokens here -> column is mixed.
		out = summarize_dataset([{"x": 1}, {"x": 2}, {"x": "nan"}, {"x": "inf"}])
		col = out["columns"]["x"]
		self.assertEqual(col["type"], "mixed")
		for v in col.values():
			if isinstance(v, float):
				self.assertTrue(math.isfinite(v))

	def test_real_nan_float_excluded(self):
		out = summarize_dataset([{"x": 1.0}, {"x": 2.0}, {"x": float("nan")}])
		self.assertEqual(out["columns"]["x"]["type"], "mixed")  # the nan float is not numeric

	def test_long_strings_not_conflated(self):
		a = "x" * 300 + "A"
		b = "x" * 300 + "B"  # shares a 300-char prefix; differs only at the end
		out = summarize_dataset([{"u": a}, {"u": b}, {"u": a}])
		col = out["columns"]["u"]
		self.assertEqual(col["distinct"], 2)  # full-value key, not a 200-char prefix
		self.assertEqual(col["top"][0]["count"], 2)
		self.assertLessEqual(len(col["top"][0]["value"]), 84)  # display truncated


if __name__ == "__main__":
	unittest.main()
