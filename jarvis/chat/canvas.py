"""Artifact handling for the chat surface — render openclaw's file outputs inline.

openclaw's agent emits rich outputs (charts, reports, PDFs, images, exports) by
writing a file under the container's ``~/.openclaw/canvas/`` (including
subdirectories) and referencing its path in the reply; the gateway serves it at
``/__openclaw__/canvas/<path>``. The live WS stream does NOT carry file content
blocks, so this is the mechanism for getting them.

This module detects every artifact the agent referenced this turn, fetches it
from the gateway (binary-safe), persists it as a private Frappe File on the
assistant message, and stamps a ``canvas`` JSON field
``[{name, title, type, file_url}]`` so the UI renders it by type:
HTML/SVG inline (iframe srcdoc), PDF embedded, images shown, and anything else
(xlsx/csv/…) offered as a download card.
"""

from __future__ import annotations

import re

import frappe

MSG = "Jarvis Chat Message"

# Cap how many artifacts we'll fetch per turn (defensive).
_MAX_CANVAS_PER_TURN = 8

# Supported artifact extension -> render type.
#   html/svg -> sandboxed iframe srcdoc
#   pdf      -> iframe/embed (browser PDF viewer)
#   image    -> <img>
#   file     -> download card (no inline render)
_EXT_TYPE = {
	"html": "html", "htm": "html", "svg": "svg",
	"pdf": "pdf",
	"png": "image", "jpg": "image", "jpeg": "image", "gif": "image", "webp": "image",
	"xlsx": "file", "xls": "file", "csv": "file", "json": "file", "txt": "file", "md": "file",
}
# Longest-first so the alternation matches "html" before "htm", "jpeg" before "jpg".
_EXTS = "|".join(sorted(_EXT_TYPE, key=len, reverse=True))

# A canvas reference: ".../canvas/<path-incl-subdirs>.<ext>". The path allows
# nested subdirs (canvas/charts/foo.html). ``(?![\w])`` stops "foo.htmlx" from
# matching as "foo.html".
_PATH = r"(?:[\w.\-]+/)*[\w.\-]+"
_CANVAS_REF = re.compile(rf"canvas/({_PATH}\.(?:{_EXTS}))(?![\w])", re.IGNORECASE)

# Markdown link / bare path to a canvas artifact — stripped from the visible
# reply (the artifact renders inline below, so the container-path link is noise).
_CANVAS_LINK = re.compile(
	rf"\[[^\]]*\]\(\s*\S*?canvas/{_PATH}\.(?:{_EXTS})\S*?\s*\)", re.IGNORECASE
)
_CANVAS_BARE = re.compile(rf"\S*?canvas/{_PATH}\.(?:{_EXTS})(?![\w])", re.IGNORECASE)


def detect_canvas_names(text: str) -> list[str]:
	"""Return canvas artifact paths referenced in ``text``, de-duplicated, in order.

	Paths keep their subdir (e.g. ``charts/sales.html``) so the gateway fetch
	hits the right URL.
	"""
	if not text:
		return []
	seen: dict[str, None] = {}
	for m in _CANVAS_REF.finditer(text):
		seen.setdefault(m.group(1), None)
	return list(seen)[:_MAX_CANVAS_PER_TURN]


def _type_for(name: str) -> str:
	ext = name.rsplit(".", 1)[-1].lower()
	return _EXT_TYPE.get(ext, "file")


def _http_base(agent_url: str) -> str:
	"""ws://host:port → http://host:port (gateway HTTP shares the WS port)."""
	base = (agent_url or "").strip().rstrip("/")
	if base.startswith("ws://"):
		return "http://" + base[len("ws://"):]
	if base.startswith("wss://"):
		return "https://" + base[len("wss://"):]
	return base


def fetch_canvas(agent_url: str, token: str, name: str) -> tuple[bytes, str] | None:
	"""GET one artifact from the gateway (binary-safe). Returns (raw_bytes, type)
	or None if it can't be fetched."""
	import requests

	base = _http_base(agent_url)
	if not base or not token:
		return None
	url = f"{base}/__openclaw__/canvas/{name}"
	try:
		r = requests.get(
			url, headers={"Authorization": f"Bearer {token}"}, timeout=20
		)
	except Exception:
		return None
	if r.status_code != 200 or not r.content:
		return None
	return r.content, _type_for(name)


def _title_for(name: str, content: bytes | None, typ: str) -> str:
	"""Prefer the artifact's own <title> (text types); else prettify the
	filename (charts/sales-this-month.svg → "Sales This Month")."""
	base = name.rsplit("/", 1)[-1]
	if typ in ("html", "svg") and content:
		try:
			text = content.decode("utf-8", "ignore")
			m = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
			if m and m.group(1).strip():
				return m.group(1).strip()[:120]
		except Exception:
			pass
	stem = re.sub(r"\.\w+$", "", base).replace("-", " ").replace("_", " ").strip()
	return stem.title() or base


def _save_file(message_name: str, name: str, content: bytes) -> str:
	"""Persist artifact bytes as a private File attached to the message. The File
	is named after the basename (subdir stripped). Returns file_url."""
	from frappe.utils.file_manager import save_file

	f = save_file(name.rsplit("/", 1)[-1], content, MSG, message_name, is_private=1)
	return f.file_url


def strip_canvas_refs(content: str, names: list[str]) -> str:
	"""Remove the dead container-path artifact link(s) from the visible reply so
	the user sees clean text + the rendered artifact, not a broken file link."""
	if not content or not names:
		return content
	out = _CANVAS_LINK.sub("", content)
	out = _CANVAS_BARE.sub("", out)
	out = re.sub(r"[ \t]+([.,;:])", r"\1", out)
	out = re.sub(r"\n{3,}", "\n\n", out)
	return out.strip()


def persist_canvases(
	assistant_msg_name: str,
	content: str,
	agent_url: str,
	token: str,
) -> list[dict]:
	"""Detect artifacts referenced in the assistant reply, fetch each from the
	gateway, save as private Files, stamp the message's ``canvas`` JSON field,
	strip the dead links, and return ``[{name, title, type, file_url}]``."""
	names = detect_canvas_names(content)
	if not names:
		return []

	items: list[dict] = []
	for name in names:
		fetched = fetch_canvas(agent_url, token, name)
		if not fetched:
			continue
		body, typ = fetched
		try:
			file_url = _save_file(assistant_msg_name, name, body)
		except Exception:
			frappe.log_error(
				title="chat canvas: save_file failed",
				message=f"name={name!r} msg={assistant_msg_name!r}\n\n{frappe.get_traceback()}",
			)
			continue
		items.append({
			"name": name,
			"title": _title_for(name, body, typ),
			"type": typ,
			"file_url": file_url,
		})

	if not items:
		return []

	cleaned = strip_canvas_refs(content, [i["name"] for i in items])
	frappe.db.set_value(MSG, assistant_msg_name, {
		"content": cleaned,
		"canvas": frappe.as_json(items),
	})
	frappe.db.commit()
	return items
