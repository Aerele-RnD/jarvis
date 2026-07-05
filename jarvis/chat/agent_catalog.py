"""Marketplace catalog sync: registry.json -> Jarvis Agent Listing rows.

The catalog is a BUNDLED deploy artifact (``jarvis/agents/registry.json``),
NEVER fetched from anywhere at runtime — a poisoned catalog bundle is
third-party prompt-as-code with the user's data access, so bundles are treated
as reviewed code and shipped in the app (adversarial finding S2).

``sync_agent_listings`` upserts one ``Jarvis Agent Listing`` per registry agent
(keyed by ``agent_slug`` — the doc name, via ``naming_rule: By fieldname``, so a
re-sync is idempotent) and marks any listing no longer in the registry as
``Deprecated``. For Published agents it also loads each skill bundle's SKILL.md
body from ``jarvis/agents/skill_bundles/<agent_slug>/`` and stores it in the
``skill_bundle`` JSON so Apply can push it to the container.

This is the mirror image of ``jarvis.chat.custom_skills.build_push_payload``
(registry -> DB here; DB -> container payload there).
"""

import json
import os

import frappe

LISTING = "Jarvis Agent Listing"

_AGENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agents")
_REGISTRY_PATH = os.path.join(_AGENTS_DIR, "registry.json")
_BUNDLE_DIR = os.path.join(_AGENTS_DIR, "skill_bundles")


# --------------------------------------------------------------------------- #
# registry loading (bundled only — never a network fetch)
# --------------------------------------------------------------------------- #
def _load_registry() -> dict:
	if not os.path.isfile(_REGISTRY_PATH):
		frappe.log_error(
			title="jarvis agent catalog: registry.json missing",
			message=f"expected bundled registry at {_REGISTRY_PATH}",
		)
		return {"agents": []}
	with open(_REGISTRY_PATH) as fh:
		return json.load(fh)


def _load_bundle(agent_slug: str, bundle_paths) -> list[dict]:
	"""Resolve a registry ``skill_bundle`` (a list of repo-relative paths) into
	the list of ``{path, body}`` the doctype stores. Bodies are read from the
	BUNDLED files under ``skill_bundles/<agent_slug>/<basename>``; a missing file
	yields an empty body (logged) rather than aborting the whole sync."""
	out = []
	for p in bundle_paths or []:
		if not isinstance(p, str) or not p.strip():
			continue
		local = os.path.join(_BUNDLE_DIR, agent_slug, os.path.basename(p))
		body = ""
		if os.path.isfile(local):
			with open(local) as fh:
				body = fh.read()
		else:
			frappe.log_error(
				title="jarvis agent catalog: skill bundle missing",
				message=f"{agent_slug}: expected {local} for registry path {p}",
			)
		out.append({"path": p, "body": body})
	return out


# --------------------------------------------------------------------------- #
# sync
# --------------------------------------------------------------------------- #
def sync_agent_listings() -> dict:
	"""Upsert Jarvis Agent Listing rows from the bundled registry. Idempotent.

	Returns ``{created, updated, deprecated, total}`` for logging / the migrate
	summary. Never fetches remotely (security)."""
	reg = _load_registry()
	agents = reg.get("agents") or []
	seen_slugs = set()
	created = updated = 0

	for a in agents:
		slug = (a.get("agent_slug") or "").strip()
		if not slug:
			continue
		seen_slugs.add(slug)

		values = {
			"agent_slug": slug,
			"title": a.get("title") or slug,
			"description": a.get("description") or "",
			"category": a.get("domain") or a.get("category") or "",
			"nature": (a.get("nature") or "").strip().title() or "Auditor",
			"version": a.get("version") or "",
			"publisher": a.get("publisher") or reg.get("publisher") or "",
			"status": a.get("status") or "Draft",
			"tools_required": frappe.as_json(a.get("tools_required") or []),
			"min_apps": frappe.as_json(a.get("min_apps") or []),
			"rule_pack": a.get("rule_pack") or "",
			"skill_bundle": frappe.as_json(_load_bundle(slug, a.get("skill_bundle"))),
			"default_schedule": frappe.as_json(a.get("default_schedule") or {}),
			"validated_for_fy": a.get("validated_for_fy") or "",
		}

		if frappe.db.exists(LISTING, slug):
			doc = frappe.get_doc(LISTING, slug)
			doc.update(values)
			doc.flags.ignore_permissions = True
			doc.save()
			updated += 1
		else:
			doc = frappe.get_doc({"doctype": LISTING, **values})
			doc.flags.ignore_permissions = True
			doc.insert()
			created += 1

	# Any listing not in the current registry is retired to Deprecated (never
	# hard-deleted — installs may still reference it).
	deprecated = 0
	for name in frappe.get_all(LISTING, pluck="name"):
		if name not in seen_slugs:
			cur = frappe.db.get_value(LISTING, name, "status")
			if cur != "Deprecated":
				frappe.db.set_value(LISTING, name, "status", "Deprecated", update_modified=False)
				deprecated += 1

	frappe.db.commit()
	return {"created": created, "updated": updated, "deprecated": deprecated, "total": len(seen_slugs)}


# --------------------------------------------------------------------------- #
# DB -> container push payload (the mirror of build_push_payload for skills)
# --------------------------------------------------------------------------- #
# The container skill dir for an installed agent, namespaced ``agent-<slug>`` so
# it lives in the SEPARATE agent_skills reconcile namespace (adversarial S4:
# never let it evict the customer's own custom skills).
AGENT_PREFIX = "agent-"


def build_agent_push_payload(owner: str | None = None) -> list[dict]:
	"""Collect the ENABLED installed agents' skill bundles into the fleet push
	payload: a list of ``{slug, description, body}`` where ``slug`` is
	``agent-<agent_slug>`` and ``body`` is the rendered SKILL.md.

	Bench-global by design (one bench == one customer == one container), so all
	enabled installs on the site are pushed; ``owner`` is accepted only to scope
	tests. An empty list is a valid "remove all agent skills" reconcile."""
	filters = {"enabled": 1}
	if owner:
		filters["owner"] = owner
	installs = frappe.get_all(
		"Jarvis Agent Installation", filters=filters, fields=["agent"], order_by="agent asc"
	)
	payload = []
	for row in installs:
		listing = frappe.db.get_value(
			LISTING, row.agent, ["agent_slug", "description", "skill_bundle", "status"], as_dict=True
		)
		if not listing or listing.status != "Published":
			continue
		try:
			bundle = frappe.parse_json(listing.skill_bundle) or []
		except Exception:
			bundle = []
		for item in bundle:
			body = (item or {}).get("body") or ""
			if not body.strip():
				continue
			payload.append(
				{
					"slug": f"{AGENT_PREFIX}{listing.agent_slug}",
					"description": (listing.description or "")[:500],
					"body": body,
				}
			)
	return payload


def after_migrate() -> None:
	"""hooks.after_migrate entry: keep the catalog in lockstep with the bundled
	registry on every migrate. Best-effort — a catalog hiccup must never fail a
	migration."""
	try:
		result = sync_agent_listings()
		frappe.logger("jarvis").info(f"agent catalog synced: {result}")
	except Exception:
		frappe.log_error(
			title="jarvis agent catalog: after_migrate sync failed",
			message=frappe.get_traceback(),
		)
