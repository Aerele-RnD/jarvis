"""Canvas/chart artifact handling for the chat surface.

openclaw's agent renders rich outputs (bar/pie/line charts, dashboards) as a
standalone **HTML or SVG file** written into the container's
``~/.openclaw/canvas/`` dir and served by the gateway at
``/__openclaw__/canvas/<file>``. It pushes these to "display nodes" (Mac/iOS/
Android); a web chat isn't one, so the file just sits there and the agent says
"no connected canvas display nodes".

This module makes the /jarvis chat the display surface, the openclaw way:
detect the artifact the agent referenced this turn, fetch it from the gateway
(same bearer token the chat already holds), persist it as a private Frappe File
attached to the assistant message, and stamp a ``canvas`` JSON field on the
message so the UI renders it inline (and re-renders on reload, even after the
container is recycled — the File outlives the ephemeral canvas dir).
"""

from __future__ import annotations

import re

import frappe

MSG = "Jarvis Chat Message"

# Cap how many artifacts we'll fetch per turn (defensive against a runaway
# message that references a hundred canvas paths).
_MAX_CANVAS_PER_TURN = 6

# A canvas reference is any path segment ".../canvas/<file>.{html,htm,svg}".
# Matches all the shapes the agent emits it in: a markdown link target
# (/home/node/.openclaw/canvas/x.svg), the gateway route
# (/__openclaw__/canvas/x.html), or a bare "canvas/x.svg".
_CANVAS_REF = re.compile(r"canvas/([A-Za-z0-9._\-]+\.(?:html?|svg))", re.IGNORECASE)

# Markdown link whose target points at a canvas file — used to strip the dead
# container-path link from the visible reply (the artifact renders inline
# below, so the broken link is just noise).
_CANVAS_LINK = re.compile(
	r"\[[^\]]*\]\(\s*\S*?canvas/[A-Za-z0-9._\-]+\.(?:html?|svg)\S*?\s*\)",
	re.IGNORECASE,
)
# Bare canvas path mention (no markdown link) — also stripped from the reply.
_CANVAS_BARE = re.compile(
	r"\S*?canvas/[A-Za-z0-9._\-]+\.(?:html?|svg)", re.IGNORECASE
)


def detect_canvas_names(text: str) -> list[str]:
	"""Return canvas filenames referenced in ``text``, de-duplicated, in order."""
	if not text:
		return []
	seen: dict[str, None] = {}
	for m in _CANVAS_REF.finditer(text):
		seen.setdefault(m.group(1), None)
	return list(seen)[:_MAX_CANVAS_PER_TURN]


def _http_base(agent_url: str) -> str:
	"""ws://host:port → http://host:port (gateway HTTP shares the WS port)."""
	base = (agent_url or "").strip().rstrip("/")
	if base.startswith("ws://"):
		return "http://" + base[len("ws://"):]
	if base.startswith("wss://"):
		return "https://" + base[len("wss://"):]
	return base


def fetch_canvas(agent_url: str, token: str, name: str) -> tuple[str, str] | None:
	"""GET one canvas artifact from the gateway. Returns (content, type) where
	type is "svg" or "html", or None if it can't be fetched.
	"""
	import requests

	base = _http_base(agent_url)
	if not base or not token:
		return None
	url = f"{base}/__openclaw__/canvas/{name}"
	try:
		r = requests.get(
			url, headers={"Authorization": f"Bearer {token}"}, timeout=15
		)
	except Exception:
		return None
	if r.status_code != 200 or not r.text:
		return None
	ctype = "svg" if name.lower().endswith(".svg") else "html"
	return r.text, ctype


def _title_for(name: str, content: str) -> str:
	"""Prefer the artifact's own <title>; else prettify the filename
	(sales-this-month.svg → "Sales This Month")."""
	m = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
	if m and m.group(1).strip():
		return m.group(1).strip()[:120]
	stem = re.sub(r"\.(html?|svg)$", "", name, flags=re.IGNORECASE)
	stem = stem.replace("-", " ").replace("_", " ").strip()
	return stem.title() or name


def _save_file(message_name: str, name: str, content: str) -> str:
	"""Persist canvas content as a private File attached to the message.
	Returns the file_url. A second canvas with the same name on the same
	message reuses the existing File (overwrite-by-replace)."""
	from frappe.utils.file_manager import save_file

	f = save_file(
		name, content, MSG, message_name, is_private=1
	)
	return f.file_url


def strip_canvas_refs(content: str, names: list[str]) -> str:
	"""Remove the dead container-path canvas link(s) from the visible reply so
	the user sees clean text + the rendered chart, not a broken file link."""
	if not content or not names:
		return content
	out = _CANVAS_LINK.sub("", content)
	out = _CANVAS_BARE.sub("", out)
	# Tidy up artefacts left behind ("Here's the chart: ." → "Here's the chart.")
	out = re.sub(r"[ \t]+([.,;:])", r"\1", out)
	out = re.sub(r"\n{3,}", "\n\n", out)
	return out.strip()


def persist_canvases(
	assistant_msg_name: str,
	content: str,
	agent_url: str,
	token: str,
) -> list[dict]:
	"""Detect canvas artifacts referenced in the assistant reply, fetch each
	from the gateway, save as private Files, stamp the message's ``canvas``
	JSON field, strip the dead links from ``content``, and return the list of
	``{name, title, type, file_url}`` items (empty if none).
	"""
	names = detect_canvas_names(content)
	if not names:
		return []

	items: list[dict] = []
	for name in names:
		fetched = fetch_canvas(agent_url, token, name)
		if not fetched:
			continue
		body, ctype = fetched
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
			"title": _title_for(name, body),
			"type": ctype,
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
