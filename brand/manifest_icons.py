#!/usr/bin/env python3
"""Reproducible source for the PWA manifest icons.

The five PNGs in jarvis/public/manifest/ were made by hand with no source file.
This renders them from the same brand definition the rest of the pack uses.

By default it only reports. Replacing the live icons changes what every
customer sees in their browser tab and on their home screen, so writing them is
opt-in behind --write.

    python brand/manifest_icons.py             compare and report
    python brand/manifest_icons.py --write     overwrite the live icons
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate import PngRenderer, _encode

MANIFEST_DIR = Path(__file__).resolve().parent.parent / "jarvis" / "public" / "manifest"

# bleed=True skips the rounded corners. Android masks maskable icons itself, and
# iOS masks the apple-touch icon, so both must fill the full square.
ICONS = {
	"icon-192.png": (192, False),
	"icon-512.png": (512, False),
	"icon-192-maskable.png": (192, True),
	"icon-512-maskable.png": (512, True),
	"apple-touch-180.png": (180, True),
}


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"--write", action="store_true", help="overwrite the live icons instead of only reporting"
	)
	args = parser.parse_args()

	rendered = render_all()
	if args.write:
		for name, payload in rendered.items():
			(MANIFEST_DIR / name).write_bytes(payload)
		print(f"wrote {len(rendered)} icons to {MANIFEST_DIR}")
		return 0

	return report(rendered)


def render_all() -> dict[str, bytes]:
	renderer = PngRenderer()
	return {name: _encode(renderer.tile(size, bleed=bleed)) for name, (size, bleed) in ICONS.items()}


def report(rendered: dict[str, bytes]) -> int:
	"""Name every live icon that differs from the current brand definition."""
	differing = []
	for name, payload in rendered.items():
		live = MANIFEST_DIR / name
		if not live.exists() or live.read_bytes() != payload:
			differing.append(name)

	if not differing:
		print(f"all {len(rendered)} manifest icons match the brand definition")
		return 0

	print("These live icons do NOT match brand/generate.py:")
	for name in sorted(differing):
		print(f"  {name}")
	print("\nThe live icons predate the current --brand-1/--brand-2 in main.css.")
	print("Run with --write to regenerate them. That changes the tab and home-screen")
	print("icon for every customer, so treat it as its own decision.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
