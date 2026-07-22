"""Guards the brand pack in brand/ against drifting from the shipping app.

JarvisMark.vue calls itself the single source of truth for the brand glyph so
that consuming surfaces cannot diverge on a refresh. brand/generate.py holds a
second copy of that glyph and of the two brand colours, which is a real drift
risk. These tests turn a silent divergence into a loud CI failure naming both
files, without putting any build-time coupling into the shipping component.

No database access. Runs as a plain unit test:
  bench --site <site> run-tests --module jarvis.tests.test_brand_assets
"""

import importlib.util
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MARK_VUE = REPO_ROOT / "frontend" / "src" / "components" / "JarvisMark.vue"
MAIN_CSS = REPO_ROOT / "frontend" / "src" / "main.css"
GENERATE_PY = REPO_ROOT / "brand" / "generate.py"


def load_generate():
	spec = importlib.util.spec_from_file_location("jarvis_brand_generate", GENERATE_PY)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class TestBrandGlyphDrift(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.brand = load_generate()

	def test_glyph_path_matches_jarvis_mark_component(self):
		"""The exported glyph is the same polygon the app renders."""
		match = re.search(r'<path\s+d="([^"]+)"', MARK_VUE.read_text())
		self.assertIsNotNone(match, f"no <path d=...> found in {MARK_VUE}")

		component_path = _normalise(match.group(1))
		self.assertEqual(
			component_path,
			_normalise(self.brand.GLYPH_PATH),
			"Brand glyph drift: the path in JarvisMark.vue no longer matches "
			"GLYPH_PATH in brand/generate.py. Update both, then re-run "
			"`python brand/generate.py`.",
		)

	def test_glyph_points_match_the_path(self):
		"""GLYPH_POINTS is what Pillow draws, so it must track GLYPH_PATH."""
		self.assertEqual(
			_points_from_path(self.brand.GLYPH_PATH),
			[tuple(float(n) for n in point) for point in self.brand.GLYPH_POINTS],
			"GLYPH_POINTS and GLYPH_PATH disagree inside brand/generate.py.",
		)

	def test_brand_colours_match_main_css(self):
		css = MAIN_CSS.read_text()
		for variable, expected in (("--brand-1", self.brand.BRAND_1), ("--brand-2", self.brand.BRAND_2)):
			match = re.search(rf"{variable}:\s*(#[0-9a-fA-F]{{3,8}})\s*;", css)
			self.assertIsNotNone(match, f"{variable} not found in {MAIN_CSS}")
			self.assertEqual(
				match.group(1).lower(),
				expected.lower(),
				f"Brand colour drift: {variable} in main.css no longer matches "
				f"brand/generate.py. Update both, then re-run `python brand/generate.py`.",
			)


class TestBrandAssetsCommitted(unittest.TestCase):
	"""The committed pack must be what the current definition produces."""

	def test_committed_assets_are_current(self):
		brand = load_generate()
		stale = [
			name
			for name, payload in brand.build_assets().items()
			if not (brand.ROOT / name).exists() or (brand.ROOT / name).read_bytes() != payload
		]
		self.assertEqual(
			stale,
			[],
			"Committed brand assets are stale. Re-run `python brand/generate.py`.",
		)


def _normalise(path: str) -> str:
	return " ".join(path.split()).upper()


def _points_from_path(path: str) -> list[tuple[float, float]]:
	"""Parse the lines-only path into its vertices."""
	numbers = re.findall(r"-?\d+(?:\.\d+)?", path)
	return [(float(numbers[i]), float(numbers[i + 1])) for i in range(0, len(numbers), 2)]


if __name__ == "__main__":
	unittest.main()
