"""Unit tests for jarvis.chat.canvas — the pure detection/strip/title helpers
that turn an agent reply referencing an openclaw canvas artifact into
render-ready metadata. Network (fetch) + File persistence are covered by the
worker integration path, not here.
"""

import unittest

from jarvis.chat import canvas


class TestCanvasDetection(unittest.TestCase):
	def test_detect_markdown_link_html_and_svg(self):
		self.assertEqual(
			canvas.detect_canvas_names(
				"Here's the chart: [sales-this-month.svg]"
				"(/home/node/.openclaw/canvas/sales-this-month.svg)"
			),
			["sales-this-month.svg"],
		)
		self.assertEqual(
			canvas.detect_canvas_names(
				"created [x](/home/node/.openclaw/canvas/sales-june-2026.html)"
			),
			["sales-june-2026.html"],
		)

	def test_detect_gateway_route_and_bare_path(self):
		self.assertEqual(
			canvas.detect_canvas_names("see /__openclaw__/canvas/foo.html"),
			["foo.html"],
		)
		self.assertEqual(canvas.detect_canvas_names("canvas/bar.htm here"), ["bar.htm"])

	def test_detect_none(self):
		self.assertEqual(canvas.detect_canvas_names("no charts, just 32,000 INR"), [])
		self.assertEqual(canvas.detect_canvas_names(""), [])
		# a non-canvas .html path must not match
		self.assertEqual(canvas.detect_canvas_names("see /var/www/index.html"), [])

	def test_dedup_and_cap(self):
		self.assertEqual(
			canvas.detect_canvas_names("canvas/a.svg then canvas/a.svg again"),
			["a.svg"],
		)
		many = " ".join(f"canvas/c{i}.svg" for i in range(12))
		self.assertEqual(len(canvas.detect_canvas_names(many)), canvas._MAX_CANVAS_PER_TURN)

	def test_strip_removes_dead_link(self):
		out = canvas.strip_canvas_refs(
			"Here's the chart: [a.svg](/home/node/.openclaw/canvas/a.svg)", ["a.svg"]
		)
		self.assertNotIn("canvas/a.svg", out)
		self.assertNotIn("](", out)
		self.assertIn("Here's the chart", out)

	def test_strip_noop_without_names(self):
		text = "plain reply, no chart"
		self.assertEqual(canvas.strip_canvas_refs(text, []), text)

	def test_title_from_filename(self):
		self.assertEqual(canvas._title_for("sales-this-month.svg", ""), "Sales This Month")
		self.assertEqual(canvas._title_for("q3_report.html", ""), "Q3 Report")

	def test_title_prefers_html_title_tag(self):
		self.assertEqual(
			canvas._title_for("x.html", "<title>Submitted Sales - June 2026</title>"),
			"Submitted Sales - June 2026",
		)

	def test_http_base_ws_to_http(self):
		self.assertEqual(canvas._http_base("ws://127.0.0.1:19000"), "http://127.0.0.1:19000")
		self.assertEqual(canvas._http_base("wss://host:443/"), "https://host:443")
		self.assertEqual(canvas._http_base(""), "")


if __name__ == "__main__":
	unittest.main()
