"""Marketplace catalog sync: registry.json -> Jarvis Agent Listing rows.

The catalog is a BUNDLED deploy artifact (``jarvis/agents/registry.json``),
NEVER fetched from anywhere at runtime — a poisoned catalog bundle is
third-party prompt-as-code with the user's data access, so bundles are treated
as reviewed code and shipped in the app (adversarial finding S2).

``sync_agent_listings`` upserts one ``Jarvis Agent Listing`` per registry agent
(keyed by ``agent_slug`` — the doc name, via ``naming_rule: By fieldname``, so a
re-sync is idempotent) and marks any listing no longer in the registry as
``Deprecated``.

Delivery is per-agent (``registry.delivery``): ``legacy`` agents load each skill
bundle's SKILL.md body from ``jarvis/agents/skill_bundles/<agent_slug>/`` into the
``skill_bundle`` JSON so Apply can push it from the bench (the old path).
``delegate`` agents ship a STUB — every catalog field EXCEPT the body, which must
NEVER enter the customer DB (A2): the bench emits only an enablement signal and
admin looks the SKILL up from the private bundle store keyed by slug (Phase 2C).

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

		# Delivery kind (Phase 0A): ``delegate`` agents ship a STUB — every
		# catalog field EXCEPT the SKILL body, which must never enter the
		# customer DB (A2): the bench emits only an enablement signal and admin
		# looks the body up from the bundle store. ``legacy`` (absent/blank
		# registry) keeps the old behaviour — the SKILL body is loaded from the
		# bundled ``skill_bundles/`` and stored in ``skill_bundle`` for the bench
		# to push. The 5 unported agents stay legacy and are untouched.
		delivery = (a.get("delivery") or "legacy").strip().lower()
		if delivery not in ("legacy", "delegate"):
			delivery = "legacy"

		# NOTE: ``allowed_roles`` is deliberately ABSENT — it is bench-admin
		# state (set via agents_api.set_agent_roles), not registry state. A
		# re-sync must never clobber an admin's role restrictions: doc.update()
		# only touches the keys given here, so the loaded child rows survive
		# the save untouched.
		values = {
			"agent_slug": slug,
			"title": a.get("title") or slug,
			"description": a.get("description") or "",
			"category": a.get("domain") or a.get("category") or "",
			"nature": (a.get("nature") or "").strip().title() or "Auditor",
			"delivery": delivery,
			"version": a.get("version") or "",
			"publisher": a.get("publisher") or reg.get("publisher") or "",
			"status": a.get("status") or "Draft",
			"tools_required": frappe.as_json(a.get("tools_required") or []),
			# A12: DocTypes the run-as user must hold read on for the agent's
			# aggregates to be numerically correct — a sibling of tools_required,
			# checkable at install/validate without leaking rule shape. For
			# delegate agents this comes from the bundle-store manifest.
			"doctypes_required": frappe.as_json(a.get("doctypes_required") or []),
			"min_apps": frappe.as_json(a.get("min_apps") or []),
			# rule_pack is a LEGACY-only pointer (the bundled scrutiny-pack id
			# evaluated by run_scrutiny). Delegate agents carry their logic in the
			# bundle store, so their registry entry has none -> empty.
			"rule_pack": a.get("rule_pack") or "",
			# A2: NEVER write a body for a delegate agent — the customer DB must
			# not hold the proprietary SKILL. Legacy agents keep the bundled body.
			"skill_bundle": (
				frappe.as_json([])
				if delivery == "delegate"
				else frappe.as_json(_load_bundle(slug, a.get("skill_bundle")))
			),
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
	"""Collect the ENABLED installed agents into the fleet push payload.

	TWO entry shapes, deliberately distinguishable so the admin relay
	(Phase 2C) can route each kind:

	* **legacy** (``delivery != "delegate"``): ``{slug, description, body}`` where
	  ``slug`` is ``agent-<agent_slug>`` and ``body`` is the rendered SKILL.md read
	  from the bench-held ``skill_bundle`` — the existing wire, UNCHANGED.
	* **delegate** (``delivery == "delegate"``, A2): an ENABLEMENT SIGNAL carrying
	  NO body — ``{slug, delivery:"delegate", tools_allow, model, timeout_s,
	  nature}``. The proprietary SKILL never transits the customer bench; admin
	  looks the body up from the bundle store keyed by slug and pushes it to fleet
	  (Phase 2C). ``tools_allow``/``timeout_s``/``nature``/``model`` echo the
	  BUNDLED registry (metadata, not IP) so admin can render the delegate.

	Bench-global by design (one bench == one customer == one container), so all
	enabled installs on the site are pushed; ``owner`` is accepted only to scope
	tests. An empty list is a valid "remove all agent skills" reconcile.

	RBAC (defense in depth): an enabled install whose OWNER's roles no longer
	permit the agent is EXCLUDED from the push — the scheduler / run-now gates
	already refuse to run it, but neither its skill bundle NOR its enablement
	signal must reach the container either."""
	# Lazy import — agents_api imports build_agent_push_payload from this module
	# at module level, so a top-level back-import would be circular.
	from jarvis.chat.agents_api import _user_allowed_for_agent

	# Delegate metadata (tools_allow / timeout_s / nature / model) lives in the
	# BUNDLED registry, never the customer DB; the enablement signal echoes it so
	# admin can render the delegate without the body transiting the bench. Indexed
	# once per build.
	reg_by_slug = {
		(a.get("agent_slug") or "").strip(): a
		for a in (_load_registry().get("agents") or [])
		if (a.get("agent_slug") or "").strip()
	}

	filters = {"enabled": 1}
	if owner:
		filters["owner"] = owner
	installs = frappe.get_all(
		"Jarvis Agent Installation",
		filters=filters,
		fields=["agent", "owner"],
		order_by="agent asc",
	)
	payload = []
	for row in installs:
		listing = frappe.db.get_value(
			LISTING,
			row.agent,
			["agent_slug", "description", "skill_bundle", "status", "delivery"],
			as_dict=True,
		)
		if not listing or listing.status != "Published":
			continue
		if not _user_allowed_for_agent(row.agent, row.owner):
			continue

		if (listing.delivery or "legacy") == "delegate":
			# A2 enablement signal — body-free. Admin resolves the SKILL from the
			# bundle store by slug (Phase 2C). Body NEVER leaves the bundle store.
			meta = reg_by_slug.get(listing.agent_slug) or {}
			payload.append(
				{
					"slug": f"{AGENT_PREFIX}{listing.agent_slug}",
					"delivery": "delegate",
					"tools_allow": meta.get("tools_allow") or [],
					"model": meta.get("model") or None,
					"timeout_s": meta.get("timeout_s"),
					"nature": (meta.get("nature") or "").strip().lower(),
				}
			)
			continue

		# Legacy: the bench-held SKILL body, unchanged wire {slug, description, body}.
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
