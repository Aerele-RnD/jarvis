"""Generate a real .xlsx workbook from tabular data and stash it as a private
File so the chat can hand the customer a download.

The agent gathers rows (typically via get_list / run_report) and passes them
here; we build the workbook with ``frappe.utils.xlsxutils.make_xlsx`` — the
same engine Frappe's own report export uses — and save the bytes as a private
File. The chat surface then renders a download card from the returned
``file_url``.
"""
import frappe

from jarvis.exceptions import InvalidArgumentError

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def export_excel(
	rows: list,
	title: str | None = None,
	columns: list | None = None,
) -> dict:
	"""Build an .xlsx from ``rows`` and return
	``{file_url, filename, mime_type, size_bytes, name}``.

	``rows`` is either a list of dicts (columns = first row's keys, or the
	given ``columns``) or a list of lists (first row is the header unless
	``columns`` is given). ``title`` names the sheet + file.
	"""
	if not isinstance(rows, list) or not rows:
		raise InvalidArgumentError("rows must be a non-empty list")

	first = rows[0]
	if isinstance(first, dict):
		cols = columns or list(first.keys())
		data = [list(cols)]
		data += [[_cell(r.get(c)) for c in cols] for r in rows if isinstance(r, dict)]
	elif isinstance(first, (list, tuple)):
		data = ([list(columns)] if columns else []) + [list(r) for r in rows]
	else:
		raise InvalidArgumentError("rows must be a list of dicts or a list of lists")

	from frappe.utils.xlsxutils import make_xlsx

	sheet = (title or "Sheet1")[:31]  # Excel caps sheet names at 31 chars
	xlsx = make_xlsx(data, sheet)  # io.BytesIO
	content = xlsx.getvalue()

	from frappe.utils.file_manager import save_file

	safe = (title or "export").replace(" ", "-").replace("/", "-")[:60] or "export"
	fdoc = save_file(f"{safe}.xlsx", content, None, None, is_private=1)
	return {
		"file_url": fdoc.file_url,
		"filename": fdoc.file_name,
		"title": title or "Export",  # clean title for the chat artifact card
		"mime_type": _XLSX_MIME,
		"size_bytes": int(fdoc.file_size or len(content)),
		"name": fdoc.name,
	}


def _cell(v):
	if v is None:
		return ""
	if isinstance(v, (dict, list)):
		return frappe.as_json(v)
	return v
