"""Tests for read_file's OCR path (needs the tesseract engine + DB).

If the OCR engine isn't installed the suite skips, so CI without tesseract
doesn't fail. Inserts (File docs) are rolled back by FrappeTestCase.
"""

import io

import frappe
from frappe.tests.utils import FrappeTestCase

from jarvis.tools.read_file import _ocr_available, read_file


def _font(size=44):
	from PIL import ImageFont

	try:
		return ImageFont.load_default(size=size)
	except TypeError:
		return ImageFont.load_default()


def _text_png(text="INVOICE TOTAL 1234"):
	from PIL import Image, ImageDraw

	im = Image.new("RGB", (640, 120), "white")
	ImageDraw.Draw(im).text((15, 30), text, fill="black", font=_font())
	buf = io.BytesIO()
	im.save(buf, "PNG")
	return buf.getvalue()


def _text_pdf(text="INVOICE TOTAL 1234"):
	from PIL import Image

	im = Image.open(io.BytesIO(_text_png(text))).convert("RGB")
	buf = io.BytesIO()
	im.save(buf, "PDF", resolution=100.0)  # image-only PDF = "scanned", no text layer
	return buf.getvalue()


def _save(name, content):
	from frappe.utils.file_manager import save_file

	return save_file(name, content, None, None, is_private=1)


class TestReadFileOCR(FrappeTestCase):
	def setUp(self):
		if not _ocr_available():
			self.skipTest("tesseract OCR engine not installed")

	def test_image_ocr_opt_in(self):
		f = _save("jt_ocr.png", _text_png())
		out = read_file(file_url=f.file_url, ocr=True)
		self.assertTrue(out.get("ocr"))
		self.assertIn("INVOICE", (out.get("text") or "").upper())

	def test_image_metadata_only_by_default(self):
		f = _save("jt_noocr.png", _text_png())
		out = read_file(file_url=f.file_url)  # ocr=None -> images are NOT auto-OCR'd
		self.assertNotIn("text", out)
		self.assertFalse(out.get("ocr"))

	def test_scanned_pdf_auto_ocr_fallback(self):
		f = _save("jt_scan.pdf", _text_pdf())
		out = read_file(file_url=f.file_url)  # auto: empty text layer -> OCR fallback
		self.assertTrue(out.get("ocr"))
		self.assertIn("INVOICE", (out.get("text") or "").upper())

	def test_scanned_pdf_ocr_disabled(self):
		f = _save("jt_scan2.pdf", _text_pdf())
		out = read_file(file_url=f.file_url, ocr=False)
		self.assertFalse(out.get("ocr"))
		self.assertIn("note", out)
