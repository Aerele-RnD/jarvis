"""Render composed content (a report/summary the agent assembled, not a single
DocType record) into a downloadable File — PDF, standalone HTML, or a PNG image.

This is the write-side twin of ``export_excel`` for prose/tabular *documents*.
``download_pdf`` only prints one existing record through a Print Format; a
report the agent composed from many queries has no record to print, so without
this the agent hand-builds the file with ``exec``/``browser`` and it never
reaches the user. Here we render the content with Frappe's own engines
(``md_to_html`` + ``get_pdf``) and save a private File the chat renders as a
download card.
"""

import frappe

from jarvis.exceptions import InvalidArgumentError, NoDataError

_FORMATS = {
	"pdf": ("pdf", "application/pdf"),
	"html": ("html", "text/html"),
	"png": ("png", "image/png"),
}

# Minimal, self-contained stylesheet so tables/headings read cleanly in every
# format (the HTML file opens standalone; the PDF/PNG render from the same CSS).
_CSS = """
body{font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:12px;color:#1a1a1a;line-height:1.5;margin:28px;}
h1,h2,h3,h4{color:#111;margin:1.1em 0 .4em;line-height:1.25;}
h1{font-size:20px;} h2{font-size:16px;} h3{font-size:14px;}
table{border-collapse:collapse;width:100%;margin:.7em 0;}
th,td{border:1px solid #ccc;padding:5px 8px;text-align:left;font-size:11px;
  vertical-align:top;}
th{background:#f4f4f5;font-weight:600;}
code{background:#f4f4f5;padding:0 3px;border-radius:3px;font-size:.92em;}
ul,ol{margin:.4em 0 .4em 1.2em;} p{margin:.5em 0;}
"""


def export_document(
	content: str,
	format: str = "pdf",
	title: str | None = None,
	content_is_html: bool = False,
) -> dict:
	"""Render ``content`` and return ``{file_url, filename, title, mime_type,
	size_bytes, name}`` for a private downloadable File.

	``content`` is the composed document — Markdown by default (tables,
	headings, lists all render), or raw HTML when ``content_is_html`` is set.
	``format`` is ``"pdf"`` (default), ``"html"``, or ``"png"`` (a single image
	of the rendered pages, stacked). ``title`` names the file + document.
	"""
	if not isinstance(content, str) or not content.strip():
		raise NoDataError("No content to export.")
	fmt = (format or "pdf").lower()
	if fmt not in _FORMATS:
		raise InvalidArgumentError(f"format must be one of {sorted(_FORMATS)}")

	body = content if content_is_html else frappe.utils.md_to_html(content)
	doc_title = frappe.utils.escape_html(title) if title else "Document"
	html = (
		f"<!doctype html><html><head><meta charset='utf-8'>"
		f"<title>{doc_title}</title><style>{_CSS}</style></head>"
		f"<body>{body}</body></html>"
	)

	if fmt == "html":
		payload = html.encode("utf-8")
	elif fmt == "pdf":
		from frappe.utils.pdf import get_pdf

		payload = get_pdf(html)
	else:  # png
		from frappe.utils.pdf import get_pdf

		payload = _pdf_to_png(get_pdf(html))

	if not payload:
		raise InvalidArgumentError(f"{fmt} rendering produced no content.")

	from frappe.utils.file_manager import save_file

	ext = _FORMATS[fmt][0]
	safe = (title or "document").replace(" ", "-").replace("/", "-")[:60] or "document"
	fdoc = save_file(f"{safe}.{ext}", payload, None, None, is_private=1)
	return {
		"file_url": fdoc.file_url,
		"filename": fdoc.file_name,
		"title": title or "Document",
		"mime_type": _FORMATS[fmt][1],
		"size_bytes": int(fdoc.file_size or len(payload)),
		"name": fdoc.name,
	}


def _pdf_to_png(pdf_bytes: bytes) -> bytes:
	"""Rasterize each PDF page (pypdfium2, the same engine get_file_pages uses)
	and stack them into one tall PNG so a multi-page report is a single image."""
	import io

	import pypdfium2 as pdfium
	from PIL import Image

	pdf = pdfium.PdfDocument(pdf_bytes)
	try:
		pages = [pdf[i].render(scale=2).to_pil().convert("RGB") for i in range(len(pdf))]
	finally:
		pdf.close()
	if not pages:
		return b""
	width = max(p.width for p in pages)
	canvas = Image.new("RGB", (width, sum(p.height for p in pages)), "white")
	y = 0
	for p in pages:
		canvas.paste(p, (0, y))
		y += p.height
	out = io.BytesIO()
	canvas.save(out, format="PNG")
	return out.getvalue()
