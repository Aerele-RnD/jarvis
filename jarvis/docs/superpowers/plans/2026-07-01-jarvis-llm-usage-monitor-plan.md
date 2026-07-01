# LLM Usage Monitor Implementation Plan — Plan 3 of 3

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a customer's System Manager a curated, real usage/cost view read from their tenant's own Bifrost — a Bifrost read-back path (fleet-agent → admin → customer) plus a Vue Monitor tab in the existing `/ai` page.

**Architecture:** The internal-only per-tenant Bifrost is reached by `docker exec`-ing `wget` against its own loopback (no host port). A pure curation module shapes the raw payload; a fleet-agent route returns it; an admin facade + whitelisted endpoint proxy it to the customer; a customer wrapper gates it (System-Manager, proxy-only); the Vue Monitor tab renders it with echarts.

**Tech Stack:** Python FastAPI (fleet-agent, pytest); Frappe v16 (jarvis_admin + jarvis, FrappeTestCase); Vue 3 + echarts (lazy); Node built-in test runner for pure chart builders.

**This is Plan 3 of 3.** Spec: `jarvis/docs/superpowers/specs/2026-07-01-jarvis-llm-proxy-ui-design.md`. **Depends on Plan 2** for the `/ai` `AiView.vue` shell (this plan fills its Monitor-tab placeholder) and the `getLlmConfig`/`getLlmSyncStatus` api.js wrappers (do NOT re-declare them). Independent of Plan 1.

## Global Constraints

- **`get_llm_usage` curated shape (contract + agreed additions):** `{applicable, period, tokens_in, tokens_out, cost_usd, per_model:[{model,tokens,cost}], used_vs_limit:{used_usd, limit_usd}}`. `applicable` (bool) is the proxy-vs-direct flag used END-TO-END (fleet-agent, admin, customer wrapper, frontend all use `applicable` — never `available`). The six CONTRACT keys are always present.
- **`used_vs_limit` keys are `used_usd` / `limit_usd`** everywhere (fleet curate, empty shape, customer wrapper, and the frontend gauge read). `limit_usd` is `None`/`null` when no budget ceiling is set.
- **Reachability:** the per-tenant Bifrost (`{container}-bifrost`) is internal-only (`expose:8080`, no host port). Reach it via `docker_ops.run_in_container(f"{name}-bifrost", "wget", "-qO-", "http://127.0.0.1:8080<path>")` (busybox wget ships in the image). Reject bridge-IP (not host-routable on Colima) and loopback-publish (breaks the internal-only posture).
- **Proxy-only:** DIRECT (single-model) tenants have no Bifrost → return the empty/`applicable:false` shape, never an error. Detect on the host via `docker_ops.inspect(f"{name}-bifrost")` exists&running (fleet); short-circuit on `proxy_active` (customer wrapper) BEFORE any admin round-trip.
- **Budget key mismatch:** the rendered Bifrost `config.json` key is `max_limit` (NOT `max_limit_usd`); `read_budget_limit_usd` reads `governance.budgets[0].max_limit`.
- **Never leak** docker stderr / fs paths / secrets / token material to any HTTP envelope. Raise `errors.OperationError(code, user_safe_msg)` and log the raw cause via `logging.getLogger("jarvis_fleet_agent")`.
- **No new rate limit / no persistence:** `get_llm_usage` is read-only — do NOT add `_enforce_rotate_rate_limit`. v1 reads Bifrost live (usage resets to zero on each pool re-apply because `wipe_bifrost_store` clears the store — documented, not a bug).
- **Endpoint names are the wire contract:** fleet `GET /v1/containers/{name}/llm-usage`; admin `jarvis_admin.api.tenant.get_llm_usage`; customer `jarvis.account.get_llm_usage`, `jarvis.account.get_llm_connection_status`.
- **System-Manager gate lives in the jarvis customer app** (`account.get_llm_usage`/`get_llm_connection_status` call `frappe.only_for`). Do NOT add a role check in `api.tenant.get_llm_usage` (would break the bench api_key flow — mirror `fetch_generated_media`).
- **api.js additions in this plan:** ONLY `getLlmUsage` + `getLlmConnectionStatus` (Plan 2 already added `getLlmConfig`/`getPresetCatalog`/`getLlmSyncStatus`/`saveLlmPool`).
- **Repos & run commands:** fleet-agent at `/Users/kavin/Bookkeeping-AI/jarvis/jarvis-fleet-agent` (`python -m pytest tests/ -q`); jarvis_admin at `/Users/kavin/frappe/v16/bench-16/apps/jarvis_admin` (`bench --site jarvis.admin run-tests --app jarvis_admin --module ...`); jarvis at `/Users/kavin/frappe/v16/bench-16/apps/jarvis` (`bench --site site.jarvis run-tests --module ...`; frontend `node --test` / `npm run build`, node20 on PATH). Commits target each repo's own git root.

## File Structure

**Phase D — fleet-agent read-back** (`jarvis-fleet-agent/jarvis_fleet_agent/`):
- `bifrost_usage.py` (new) + `tests/test_bifrost_usage.py` — pure curation
- `main.py` (edit) — `GET /v1/containers/{name}/llm-usage` + `tests/test_llm_usage_route.py`
- `llm-proxy` repo: `docs/reference/bifrost-usage-readback-spike.md` (spike findings)

**Phase E — admin proxy** (`jarvis_admin/jarvis_admin/`):
- `fleet/agent_client.py` (edit) — `llm_usage` verb
- `fleet/usage.py` (new) + `tests/fleet/test_usage.py` — facade
- `api/tenant.py` (edit) + `tests/api/test_get_llm_usage.py` — whitelisted endpoint

**Phase F — customer wrappers + Vue Monitor** (`jarvis/`):
- `admin_client.py` + `account.py` (edit) + `tests/test_llm_monitor.py`, `tests/test_role_gates.py` (edit)
- `frontend/src/api.js` (edit); `frontend/src/charts/usageCharts.js` + `.test.js` (new); `frontend/src/charts/EChart.vue` (new); `frontend/src/views/MonitorTab.vue` (new); `frontend/src/views/AiView.vue` (edit — mount MonitorTab)

---

## Phase D — Fleet-agent Bifrost read-back

### Task D1 — SPIKE: pin the Bifrost usage endpoint + fields + reachability (do first)

**Files:** Create `/Users/kavin/Bookkeeping-AI/llm-proxy/docs/reference/bifrost-usage-readback-spike.md` (findings only — no product code).

**Why:** the exact Bifrost usage endpoint/fields are not in any repo (grep found only `/openai/v1`, `/healthz`, `/metrics`); prior spikes needed a socat forwarder to reach the internal Bifrost. Pin spec §11.7's two unknowns.

- [ ] Boot/reuse one PROXY tenant so `{name}-bifrost` runs with a real governance config (`budget-<name>` with `max_limit`, `vk-<name>`); send 2-3 governed completions through openclaw so Bifrost records usage.
- [ ] Probe candidate endpoints from INSIDE the bifrost container (busybox wget, proven by its healthcheck):
```bash
docker exec <name>-bifrost wget -qO- http://127.0.0.1:8080/metrics | head -50
docker exec <name>-bifrost wget -qO- http://127.0.0.1:8080/api/governance/usage
docker exec <name>-bifrost wget -qO- http://127.0.0.1:8080/api/governance/virtual-keys
docker exec <name>-bifrost wget -qO- http://127.0.0.1:8080/api/logs
# if 401 (governed), retry with the VK header (VK value = the sk-bf-… in the tenant llm.key)
docker exec <name>-bifrost wget -qO- --header "x-bf-vk: sk-bf-…" http://127.0.0.1:8080/api/governance/usage
```
- [ ] Confirm the reachability winner (docker-exec + wget loopback) and explicitly REJECT bridge-IP + loopback-publish.
- [ ] Record: EXACT path (→ `BIFROST_USAGE_PATH`), whether a VK header is needed, the raw response body, and the field-name mapping to `tokens_in`/`tokens_out`/`cost_usd` + the `per_model` breakdown (`model`,`tokens`,`cost`). Save a real captured response as the Task D2 fixture.
- [ ] **Fallback if live infra is unavailable:** record the assumed shape used by Tasks D2/D3 (`/api/governance/usage`, `usage.{input_tokens,output_tokens,cost}`, `per_model[].{model,input_tokens,output_tokens,cost}`) as PROVISIONAL and flag that D2's `BIFROST_USAGE_PATH` + key mapping must be re-confirmed against a live tenant before release.
- [ ] **Commit** (in the llm-proxy repo):
```bash
cd /Users/kavin/Bookkeeping-AI/llm-proxy && git add docs/reference/bifrost-usage-readback-spike.md
git commit -m "docs: Bifrost usage read-back spike findings"
```

---

### Task D2 — `bifrost_usage.py` pure curation module (TDD)

**Files:** Create `jarvis_fleet_agent/bifrost_usage.py`, `tests/test_bifrost_usage.py`.

**Interfaces:** `empty_usage() -> dict`, `curate_usage(raw, *, budget_limit_usd) -> dict`, `read_budget_limit_usd(state_root, name) -> float|None`, const `BIFROST_USAGE_PATH`.

- [ ] **Step 1 (RED): `tests/test_bifrost_usage.py`** (use the D1 fixture; `applicable` + `used_usd`/`limit_usd`):
```python
from jarvis_fleet_agent import bifrost_usage

# SPIKE FIXTURE (Task D1) — replace with the exact recorded Bifrost body + keys.
RAW = {
    "reset_duration": "1M",
    "usage": {"input_tokens": 1200, "output_tokens": 800, "cost": 0.42},
    "per_model": [
        {"model": "anthropic/claude-opus-4-8", "input_tokens": 1000, "output_tokens": 700, "cost": 0.40},
        {"model": "openai/gpt-5.5", "input_tokens": 200, "output_tokens": 100, "cost": 0.02},
    ],
}

def test_curate_matches_contract_shape():
    out = bifrost_usage.curate_usage(RAW, budget_limit_usd=100.0)
    assert set(out) >= {"applicable", "period", "tokens_in", "tokens_out", "cost_usd", "per_model", "used_vs_limit"}
    assert out["applicable"] is True
    assert out["tokens_in"] == 1200 and out["tokens_out"] == 800 and out["cost_usd"] == 0.42
    assert out["used_vs_limit"] == {"used_usd": 0.42, "limit_usd": 100.0}
    assert out["per_model"][0] == {"model": "anthropic/claude-opus-4-8", "tokens": 1700, "cost": 0.40}

def test_empty_usage_is_zeroed_but_shaped():
    out = bifrost_usage.empty_usage()
    assert out["applicable"] is False
    assert out["tokens_in"] == 0 and out["cost_usd"] == 0.0 and out["per_model"] == []
    assert out["used_vs_limit"] == {"used_usd": 0.0, "limit_usd": None}

def test_read_budget_limit_from_config(tmp_path):
    import json
    from jarvis_fleet_agent import paths
    p = paths.bifrost_config_path(str(tmp_path), "c1")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"governance": {"budgets": [{"id": "budget-c1", "max_limit": 50.0}]}}))
    assert bifrost_usage.read_budget_limit_usd(str(tmp_path), "c1") == 50.0

def test_read_budget_limit_missing_returns_none(tmp_path):
    assert bifrost_usage.read_budget_limit_usd(str(tmp_path), "nope") is None
```
Run (from `jarvis-fleet-agent`): `python -m pytest tests/test_bifrost_usage.py -v` → RED.

- [ ] **Step 2 (GREEN): `jarvis_fleet_agent/bifrost_usage.py`** (pure; no docker, no llm_proxy):
```python
"""Curate the tenant Bifrost's raw usage/governance payload into the customer
get_llm_usage shape. Pure: dict in, dict out."""
from __future__ import annotations
import json
from jarvis_fleet_agent import paths

# SPIKE (Task D1): the exact usage path on the tenant Bifrost.
BIFROST_USAGE_PATH = "/api/governance/usage"  # confirm via bifrost-usage-readback-spike.md


def empty_usage() -> dict:
    """DIRECT tenant (no Bifrost) — contract keys zeroed; applicable flags 'no proxy'."""
    return {
        "applicable": False, "period": None, "tokens_in": 0, "tokens_out": 0,
        "cost_usd": 0.0, "per_model": [], "used_vs_limit": {"used_usd": 0.0, "limit_usd": None},
    }


def curate_usage(raw: dict, *, budget_limit_usd: float | None) -> dict:
    """Map Bifrost's usage JSON to the customer shape. Key paths are the D1-confirmed
    names; adjust only if the spike recorded different keys."""
    totals = raw.get("usage") or raw
    tin = int(totals.get("input_tokens") or 0)
    tout = int(totals.get("output_tokens") or 0)
    cost = round(float(totals.get("cost") or 0.0), 6)
    per_model = []
    for r in (raw.get("per_model") or []):
        tok = r.get("tokens")
        if tok is None:
            tok = int(r.get("input_tokens") or 0) + int(r.get("output_tokens") or 0)
        per_model.append({"model": r.get("model") or "", "tokens": int(tok),
                          "cost": round(float(r.get("cost") or 0.0), 6)})
    return {
        "applicable": True,
        "period": raw.get("reset_duration") or raw.get("period"),
        "tokens_in": tin, "tokens_out": tout, "cost_usd": cost,
        "per_model": per_model,
        "used_vs_limit": {"used_usd": cost, "limit_usd": budget_limit_usd},
    }


def read_budget_limit_usd(state_root: str, name: str) -> float | None:
    """Budget ceiling from the tenant's on-disk Bifrost config.json. Rendered key
    is `max_limit` (NOT `max_limit_usd`)."""
    p = paths.bifrost_config_path(state_root, name)
    if not p.exists():
        return None
    try:
        budgets = (json.loads(p.read_text()).get("governance") or {}).get("budgets") or []
    except (json.JSONDecodeError, OSError):
        return None
    if budgets and isinstance(budgets[0], dict) and budgets[0].get("max_limit") is not None:
        return float(budgets[0]["max_limit"])
    return None
```
Run: `python -m pytest tests/test_bifrost_usage.py -v` → GREEN.

- [ ] **Step 3: Commit** (fleet-agent repo):
```bash
cd /Users/kavin/Bookkeeping-AI/jarvis/jarvis-fleet-agent
git add jarvis_fleet_agent/bifrost_usage.py tests/test_bifrost_usage.py
git commit -m "feat: pure Bifrost usage curation module"
```

---

### Task D3 — fleet-agent `GET /v1/containers/{name}/llm-usage` route (TDD)

**Files:** edit `jarvis_fleet_agent/main.py` (add route in `build_app()` after `llm_auth_status`); create `tests/test_llm_usage_route.py`.

- [ ] **Step 1 (RED): `tests/test_llm_usage_route.py`** (mirror `test_auth_profile_endpoints.py` docker mock):
```python
import json
from unittest.mock import patch

def test_llm_usage_requires_bearer(client):
    assert client.get("/v1/containers/jarvis-x/llm-usage").status_code == 401

def test_llm_usage_direct_tenant_returns_empty(client, auth):
    with patch("jarvis_fleet_agent.main.docker_ops.inspect",
               return_value={"exists": False, "running": False, "health": "absent", "started_at": None}):
        r = client.get("/v1/containers/jarvis-x/llm-usage", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applicable"] is False and body["tokens_in"] == 0 and body["per_model"] == []
    assert body["used_vs_limit"] == {"used_usd": 0.0, "limit_usd": None}

def test_llm_usage_proxy_tenant_curated(client, auth, cfg_path):
    from jarvis_fleet_agent.config import load_config
    from jarvis_fleet_agent import paths
    cfg = load_config(cfg_path)
    bcfg = paths.bifrost_config_path(cfg.state_root, "jarvis-x")
    bcfg.parent.mkdir(parents=True, exist_ok=True)
    bcfg.write_text(json.dumps({"governance": {"budgets": [{"id": "budget-x", "max_limit": 100.0}]}}))
    raw = {"reset_duration": "1M", "usage": {"input_tokens": 10, "output_tokens": 5, "cost": 0.03},
           "per_model": [{"model": "anthropic/claude-opus-4-8", "input_tokens": 10, "output_tokens": 5, "cost": 0.03}]}
    with patch("jarvis_fleet_agent.main.docker_ops.inspect",
               return_value={"exists": True, "running": True, "health": "healthy", "started_at": "x"}), \
         patch("jarvis_fleet_agent.main.docker_ops.run_in_container",
               return_value=(0, json.dumps(raw), "")) as rc:
        r = client.get("/v1/containers/jarvis-x/llm-usage", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applicable"] is True and body["tokens_in"] == 10 and body["cost_usd"] == 0.03
    assert body["used_vs_limit"]["limit_usd"] == 100.0
    argv = rc.call_args.args
    assert argv[0] == "jarvis-x-bifrost" and "wget" in argv

def test_llm_usage_unreachable_bifrost_502(client, auth):
    with patch("jarvis_fleet_agent.main.docker_ops.inspect",
               return_value={"exists": True, "running": True, "health": "healthy", "started_at": "x"}), \
         patch("jarvis_fleet_agent.main.docker_ops.run_in_container", return_value=(-9, "", "timeout")):
        r = client.get("/v1/containers/jarvis-x/llm-usage", headers=auth)
    assert r.status_code == 502 and r.json()["error"]["code"] == "bifrost_usage_unreachable"
```
Run: `python -m pytest tests/test_llm_usage_route.py -v` → RED (404).

- [ ] **Step 2 (GREEN): add the route in `main.py`** inside `build_app()` (json + OperationError already imported; `cfg` in scope):
```python
@app.get("/v1/containers/{name}/llm-usage", dependencies=[Depends(require_bearer)])
async def llm_usage(name: ContainerName):
    """Curated, abstracted usage from the tenant's own Bifrost (proxy tenants
    only). Reaches the internal-only Bifrost by docker-exec'ing wget against its
    loopback (no host port). DIRECT tenants have no Bifrost -> empty shape. Reads
    live (usage resets to zero on each pool re-apply); no persistence."""
    from jarvis_fleet_agent import bifrost_usage
    bifrost_name = f"{name}-bifrost"
    state = docker_ops.inspect(bifrost_name)
    if not (state.get("exists") and state.get("running")):
        return bifrost_usage.empty_usage()
    rc, out, err = docker_ops.run_in_container(
        bifrost_name, "wget", "-qO-",
        f"http://127.0.0.1:8080{bifrost_usage.BIFROST_USAGE_PATH}", timeout=10)
    if rc != 0 or not out.strip():
        logging.getLogger("jarvis_fleet_agent").error(
            "bifrost usage read failed for %s: rc=%s err=%r", bifrost_name, rc, err)
        raise OperationError("bifrost_usage_unreachable", "could not read usage from the tenant proxy")
    try:
        raw = json.loads(out)
    except json.JSONDecodeError:
        logging.getLogger("jarvis_fleet_agent").error(
            "bifrost usage not JSON for %s: %r", bifrost_name, out[:200])
        raise OperationError("bifrost_usage_unparseable", "proxy usage response was not valid JSON")
    limit = bifrost_usage.read_budget_limit_usd(cfg.state_root, name)
    return bifrost_usage.curate_usage(raw, budget_limit_usd=limit)
```
Run: `python -m pytest tests/test_llm_usage_route.py tests/test_bifrost_usage.py -v` → GREEN. Full: `python -m pytest tests/ -q`.

- [ ] **Step 3: Commit** (fleet-agent repo):
```bash
git add jarvis_fleet_agent/main.py tests/test_llm_usage_route.py
git commit -m "feat: GET /v1/containers/{name}/llm-usage read-back route"
```

---

## Phase E — Admin proxy

### Task E1 — admin `agent_client.llm_usage` verb

**Files:** edit `jarvis_admin/jarvis_admin/fleet/agent_client.py`.

- [ ] **Step 1: Add after `integration_status`:**
```python
def llm_usage(host, name: str) -> dict:
    """Curated real Bifrost usage for a proxy tenant (empty shape for direct).
    GET /v1/containers/{name}/llm-usage. Read-only; short timeout."""
    return _request(host, "GET", f"/v1/containers/{name}/llm-usage", timeout=15)
```
(No standalone test — covered by Task E2's facade test which mocks this verb.)

- [ ] **Step 2: Commit** (jarvis_admin repo):
```bash
cd /Users/kavin/frappe/v16/bench-16/apps/jarvis_admin
git add jarvis_admin/fleet/agent_client.py
git commit -m "feat(admin): agent_client.llm_usage verb"
```

---

### Task E2 — admin `fleet.usage.get_llm_usage` facade (TDD)

**Files:** create `jarvis_admin/jarvis_admin/fleet/usage.py`, `jarvis_admin/jarvis_admin/tests/fleet/test_usage.py`.

- [ ] **Step 1 (RED): `tests/fleet/test_usage.py`** (mirror `tests/fleet/test_creds.py` setUp/cleanup):
```python
from unittest.mock import patch
import frappe
from frappe.tests.utils import FrappeTestCase
from jarvis_admin.fleet.usage import get_llm_usage

HOST_DT, TENANT_DT = "Jarvis Host", "Jarvis Tenant"


class TestUsageFacade(FrappeTestCase):
    def setUp(self):
        self._cleanup()
        host = frappe.get_doc({"doctype": HOST_DT, "hostname": "us-test-host",
            "host_address": "127.0.0.1", "status": "Active", "max_containers": 5,
            "tenant_url_mode": "Port", "port_range_start": 19000, "port_range_end": 19100,
            "fleet_agent_base_url": "http://h:8088", "fleet_agent_token": "tok"}).insert(ignore_permissions=True)
        self.tenant = frappe.get_doc({"doctype": TENANT_DT, "host": host.name,
            "assignment_state": "Assigned", "status": "Running", "container_name": "us-test-c1",
            "agent_port": 19000, "agent_token": "op"}).insert(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        for t in frappe.get_all(TENANT_DT, filters={"container_name": ["like", "us-test-%"]}, pluck="name"):
            frappe.delete_doc(TENANT_DT, t, force=True, ignore_permissions=True)
        for h in frappe.get_all(HOST_DT, filters={"hostname": ["like", "us-test-%"]}, pluck="name"):
            frappe.delete_doc(HOST_DT, h, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_routes_to_tenant_host_and_container(self):
        with patch("jarvis_admin.fleet.usage.agent_client.llm_usage",
                   return_value={"tokens_in": 1, "applicable": True}) as lu:
            out = get_llm_usage(self.tenant.name)
        self.assertEqual(out["tokens_in"], 1)
        self.assertEqual(lu.call_args.args[0], self.tenant.host)
        self.assertEqual(lu.call_args.args[1], "us-test-c1")

    def test_missing_tenant_raises(self):
        with self.assertRaises(frappe.DoesNotExistError):
            get_llm_usage("us-test-nope")
```
Run: `bench --site jarvis.admin run-tests --app jarvis_admin --module jarvis_admin.tests.fleet.test_usage` → RED.

- [ ] **Step 2 (GREEN): `fleet/usage.py`:**
```python
"""Read-only Bifrost usage read-back facade. Resolves tenant -> host/container
and asks the fleet-agent for curated usage. No DB write, no restart."""
import frappe
from jarvis_admin.fleet import agent_client


def _tenant_routing(tenant_name: str) -> dict:
    row = frappe.db.get_value("Jarvis Tenant", tenant_name, ["host", "container_name"], as_dict=True)
    if not row:
        raise frappe.DoesNotExistError(f"Jarvis Tenant {tenant_name!r} not found")
    return row


def get_llm_usage(tenant_name: str) -> dict:
    """Curated real Bifrost usage for the tenant (proxy only; the fleet-agent
    returns the empty shape for direct tenants)."""
    t = _tenant_routing(tenant_name)
    return agent_client.llm_usage(t.host, t.container_name)
```
Run: same command → GREEN.

- [ ] **Step 3: Commit:**
```bash
git add jarvis_admin/fleet/usage.py jarvis_admin/tests/fleet/test_usage.py
git commit -m "feat(admin): fleet.usage.get_llm_usage facade"
```

---

### Task E3 — admin whitelisted `api.tenant.get_llm_usage` (TDD)

**Files:** edit `jarvis_admin/jarvis_admin/api/tenant.py`; create `jarvis_admin/jarvis_admin/tests/api/test_get_llm_usage.py`.

- [ ] **Step 1 (RED): `tests/api/test_get_llm_usage.py`** (reuse `_make_customer/_make_host/_make_tenant/_AuthMixin/_cleanup` from `test_update_llm_pool.py`):
```python
from unittest.mock import patch
import frappe
from frappe.tests.utils import FrappeTestCase
from jarvis_admin.tests.api.test_update_llm_pool import _make_customer, _make_host, _make_tenant, _AuthMixin, _cleanup


class TestGetLlmUsage(_AuthMixin, FrappeTestCase):
    def setUp(self):
        _cleanup()
        self.customer, *_ = _make_customer("usage-test-happy@example.com")
        self.host = _make_host()
        self.tenant = _make_tenant(self.host.name, self.customer.name, "usage-test-happy-t1")

    def tearDown(self):
        _cleanup()

    def test_happy_path_returns_ok_wrapped(self):
        from jarvis_admin.api.tenant import get_llm_usage
        self._as_customer(self.customer)
        with patch("jarvis_admin.fleet.usage.get_llm_usage",
                   return_value={"tokens_in": 7, "applicable": True}) as m:
            res = get_llm_usage()
        self.assertTrue(res["ok"])
        self.assertEqual(res["data"]["tokens_in"], 7)
        self.assertEqual(m.call_args.args[0], self.tenant.name)

    def test_guest_401(self):
        from jarvis_admin.api.tenant import get_llm_usage
        frappe.set_user("Guest"); self.addCleanup(frappe.set_user, "Administrator")
        with self.assertRaises(frappe.AuthenticationError):
            get_llm_usage()

    def test_no_tenant_409(self):
        from jarvis_admin.api.tenant import get_llm_usage
        c, *_ = _make_customer("usage-test-notenant@example.com"); self._as_customer(c)
        res = get_llm_usage()
        self.assertEqual(res["error"]["code"], "NoRunningTenant")
        self.assertEqual(frappe.local.response.http_status_code, 409)

    def test_fleet_error_502(self):
        from jarvis_admin.api.tenant import get_llm_usage
        from jarvis_admin.fleet.exceptions import FleetError
        self._as_customer(self.customer)
        with patch("jarvis_admin.fleet.usage.get_llm_usage", side_effect=FleetError("agent down")):
            res = get_llm_usage()
        self.assertEqual(frappe.local.response.http_status_code, 502)
        self.assertEqual(res["error"]["code"], "FleetError")
```
Run: `bench --site jarvis.admin run-tests --app jarvis_admin --module jarvis_admin.tests.api.test_get_llm_usage` → RED.

- [ ] **Step 2 (GREEN): add to `api/tenant.py`** (near `fetch_generated_media`; NO rate limit — read-only; NO role check here):
```python
@frappe.whitelist()
@fleet_endpoint
def get_llm_usage() -> dict:
    """Curated real Bifrost usage for the customer's running tenant (monitor tab).
    PROXY tenants only; the fleet-agent returns an empty/not-applicable shape for
    DIRECT tenants. Read-only. System-Manager gating is enforced on the jarvis
    customer-app side; here auth is the customer api_key (current_customer).

      409 NoRunningTenant     - customer has no Tenant in status=running
      502 <FleetError class>  - fleet operation failed downstream
    """
    customer = current_customer()
    tenant_name = _require_running_tenant(customer.name)
    from jarvis_admin.fleet.usage import get_llm_usage as _get
    return _ok(_get(tenant_name))
```
Run: same command → GREEN. Then: `bench --site jarvis.admin run-tests --app jarvis_admin --module jarvis_admin.tests.fleet.test_usage` + fleet-agent `python -m pytest tests/ -q`.

- [ ] **Step 3: Commit:**
```bash
git add jarvis_admin/api/tenant.py jarvis_admin/tests/api/test_get_llm_usage.py
git commit -m "feat(admin): whitelisted api.tenant.get_llm_usage"
```

---

## Phase F — Customer wrappers + Vue Monitor tab

### Task F1 — customer `get_llm_usage` / `get_llm_connection_status` wrappers (TDD)

**Files:** edit `jarvis/admin_client.py`, `jarvis/account.py`; create `jarvis/tests/test_llm_monitor.py`; edit `jarvis/tests/test_role_gates.py`.

- [ ] **Step 1 (RED): `jarvis/tests/test_llm_monitor.py`:**
```python
from unittest.mock import patch
import frappe
from frappe.tests.utils import FrappeTestCase
from jarvis import account, admin_client
from jarvis.exceptions import AdminValidationError


class TestGetLlmUsage(FrappeTestCase):
    def setUp(self):
        self._proxy = frappe.db.get_single_value("Jarvis Settings", "proxy_active")

    def tearDown(self):
        frappe.db.set_single_value("Jarvis Settings", "proxy_active", self._proxy or 0)
        frappe.db.commit()

    def test_direct_tenant_returns_empty_shape_without_admin_call(self):
        frappe.db.set_single_value("Jarvis Settings", "proxy_active", 0); frappe.db.commit()
        with patch.object(admin_client, "get_llm_usage") as m:
            out = account.get_llm_usage()
        m.assert_not_called()
        self.assertEqual(out["applicable"], False)
        self.assertEqual(out["per_model"], [])
        self.assertEqual(out["used_vs_limit"], {"used_usd": 0.0, "limit_usd": None})

    def test_proxy_tenant_passes_admin_payload_through(self):
        frappe.db.set_single_value("Jarvis Settings", "proxy_active", 1); frappe.db.commit()
        fake = {"applicable": True, "period": "1M", "tokens_in": 10, "tokens_out": 20, "cost_usd": 0.42,
                "per_model": [{"model": "gpt-5.5", "tokens": 30, "cost": 0.42}],
                "used_vs_limit": {"used_usd": 0.42, "limit_usd": 5.0}}
        with patch.object(admin_client, "get_llm_usage", return_value=fake) as m:
            out = account.get_llm_usage()
        m.assert_called_once_with()
        self.assertEqual(out["applicable"], True)
        self.assertEqual(out["cost_usd"], 0.42)
        self.assertEqual(out["per_model"][0]["model"], "gpt-5.5")

    def test_admin_validation_error_surfaces_as_frappe_throw(self):
        frappe.db.set_single_value("Jarvis Settings", "proxy_active", 1); frappe.db.commit()
        with patch.object(admin_client, "get_llm_usage", side_effect=AdminValidationError("bifrost unreachable")):
            with self.assertRaises(frappe.ValidationError):
                account.get_llm_usage()


class TestGetLlmConnectionStatus(FrappeTestCase):
    def test_remaps_admin_auth_status_fields(self):
        raw = {"ok": True, "data": {"auth_profile_present": True, "profile_ids": ["openai"],
               "default_model": "gpt-5.5", "openai_profile_expires_ms": 1893456000000}}
        with patch.object(admin_client, "post_llm_auth_status", return_value=raw) as m:
            out = account.get_llm_connection_status()
        m.assert_called_once_with()
        self.assertEqual(out["auth_present"], True)
        self.assertEqual(out["oauth_expires_at"], 1893456000000)
        self.assertEqual(out["default_model"], "gpt-5.5")
```
Run: `bench --site site.jarvis run-tests --module jarvis.tests.test_llm_monitor` → RED.

- [ ] **Step 2 (GREEN): add the bench-side caller to `admin_client.py`** (next to `post_llm_auth_status`):
```python
def get_llm_usage() -> dict:
    """Curated real Bifrost usage for the customer's tenant (monitor tab).
    Chain: fleet-agent /llm-usage -> admin api.tenant.get_llm_usage -> here.
    Raises AdminAuthError / AdminUnreachableError / AdminValidationError."""
    return _post(path="/api/method/jarvis_admin.api.tenant.get_llm_usage", body={})
```

- [ ] **Step 3 (GREEN): add the customer wrappers to `account.py`** (after `is_ready_for_chat`; `_surface` imported from `jarvis.onboarding`):
```python
@frappe.whitelist()
def get_llm_usage() -> dict:
    """Real, curated Bifrost usage for the Monitor tab (System-Manager only,
    spec 7). DIRECT tenants (proxy_active=0, no Bifrost) short-circuit to the
    empty shape — no pointless admin round-trip."""
    frappe.only_for("System Manager")
    settings = frappe.get_single("Jarvis Settings")
    if not getattr(settings, "proxy_active", 0):
        return {"applicable": False, "period": None, "tokens_in": 0, "tokens_out": 0,
                "cost_usd": 0.0, "per_model": [],
                "used_vs_limit": {"used_usd": 0.0, "limit_usd": None}}
    data = _surface(admin_client.get_llm_usage) or {}
    data["applicable"] = True
    return data


@frappe.whitelist()
def get_llm_connection_status() -> dict:
    """Connection card for the Monitor tab: auth profile present + OAuth expiry.
    Wrapper over admin_client.post_llm_auth_status, remapped to the customer
    contract field names. Never returns token material. System-Manager only."""
    frappe.only_for("System Manager")
    raw = _surface(admin_client.post_llm_auth_status) or {}
    data = raw.get("data", raw) or {}
    return {
        "auth_present": bool(data.get("auth_profile_present")),
        "oauth_expires_at": data.get("openai_profile_expires_ms"),
        "profile_ids": data.get("profile_ids", []),
        "default_model": data.get("default_model", ""),
    }
```
(Confirm `from jarvis.onboarding import _surface` is imported in `account.py`; it already backs `get_account`.)

- [ ] **Step 4: Extend `test_role_gates.py`** `GATED_ENDPOINTS`:
```python
    ("jarvis.account", "get_llm_usage", {}),
    ("jarvis.account", "get_llm_connection_status", {}),
```
Run: `bench --site site.jarvis run-tests --module jarvis.tests.test_llm_monitor` and `--module jarvis.tests.test_role_gates` → GREEN.

- [ ] **Step 5: Commit** (jarvis repo):
```bash
cd /Users/kavin/frappe/v16/bench-16/apps/jarvis
git add jarvis/admin_client.py jarvis/account.py jarvis/tests/test_llm_monitor.py jarvis/tests/test_role_gates.py
git commit -m "feat: customer get_llm_usage + get_llm_connection_status wrappers"
```

---

### Task F2 — api.js Monitor wrappers

**Files:** edit `frontend/src/api.js`.

- [ ] **Step 1: Add ONLY the two new wrappers** (getLlmConfig/getLlmSyncStatus already exist from Plan 2 — do NOT re-declare):
```js
// --- LLM Monitor (System-Manager gated server-side). Real Bifrost usage, NOT the getUsage estimate. ---
export const getLlmUsage = () => call("jarvis.account.get_llm_usage")
export const getLlmConnectionStatus = () => call("jarvis.account.get_llm_connection_status")
```

- [ ] **Step 2: Build + Commit:** `cd frontend && npm run build` (exit 0);
```bash
git add frontend/src/api.js && git commit -m "feat(fe): api.js monitor wrappers"
```

---

### Task F3 — `usageCharts.js` pure gauge + per-model builders (TDD)

**Files:** Create `frontend/src/charts/usageCharts.js`, `frontend/src/charts/usageCharts.test.js`.

**Interfaces:** `budgetGaugeOption(used, limit, dark=false) -> option|null` (null when `limit<=0`); `perModelBarSpec(perModel, metric="tokens") -> chartTheme bar spec`.

- [ ] **Step 1 (RED): `usageCharts.test.js`:**
```js
import { test } from "node:test"
import assert from "node:assert/strict"
import { budgetGaugeOption, perModelBarSpec } from "./usageCharts.js"
import { buildOption } from "./chartTheme.js"

test("gauge: null when no positive limit", () => {
  assert.equal(budgetGaugeOption(5, 0), null)
  assert.equal(budgetGaugeOption(5, -1), null)
})
test("gauge: percent, caps at 100, red at >=90%", () => {
  const o = budgetGaugeOption(45, 100)
  assert.equal(o.series[0].type, "gauge")
  assert.equal(o.series[0].data[0].value, 45)
  const over = budgetGaugeOption(150, 100)
  assert.equal(over.series[0].data[0].value, 100)
  assert.equal(over.series[0].progress.itemStyle.color, "#fc8181")
})
test("perModelBarSpec: chartTheme-renderable bar spec", () => {
  const s = perModelBarSpec([{ model: "gpt-5.5", tokens: 10, cost: 0.2 }], "tokens")
  assert.equal(s.type, "bar")
  assert.deepEqual(s.x, ["gpt-5.5"])
  assert.deepEqual(s.series[0].data, [10])
  assert.notEqual(buildOption(s), null)
  const cost = perModelBarSpec([{ model: "m", tokens: 10, cost: 0.2 }], "cost")
  assert.deepEqual(cost.series[0].data, [0.2])
})
```
Run (RED): `cd frontend && node --test src/charts/usageCharts.test.js`

- [ ] **Step 2 (GREEN): `usageCharts.js`** (no echarts import; colors mirror chartTheme):
```js
// Pure builders for the LLM Monitor echarts (plain option objects; node:test-able).
const GREEN = "#48bb74", AMBER = "#f6ad55", RED = "#fc8181"

export function budgetGaugeOption(used, limit, dark = false) {
  const lim = Number(limit) || 0
  if (lim <= 0) return null
  const val = Math.max(0, Number(used) || 0)
  const pct = Math.min(100, Math.round((val / lim) * 100))
  const text = dark ? "#cbd5e0" : "#333333"
  const track = dark ? "#2d3748" : "#e2e8f0"
  const color = pct >= 90 ? RED : pct >= 70 ? AMBER : GREEN
  return {
    series: [{
      type: "gauge", startAngle: 210, endAngle: -30, min: 0, max: 100,
      progress: { show: true, width: 14, itemStyle: { color } },
      axisLine: { lineStyle: { width: 14, color: [[1, track]] } },
      axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
      pointer: { show: false }, anchor: { show: false },
      detail: { valueFormatter: (v) => `${v}%`, color: text, fontSize: 22, offsetCenter: [0, "10%"] },
      data: [{ value: pct }],
    }],
  }
}

export function perModelBarSpec(perModel, metric = "tokens") {
  const rows = Array.isArray(perModel) ? perModel : []
  return {
    type: "bar",
    x: rows.map((r) => String(r.model || "")),
    series: [{ name: metric === "cost" ? "Cost ($)" : "Tokens", data: rows.map((r) => Number(r[metric]) || 0) }],
    options: { horizontal: true },
  }
}
```
Run (GREEN): `node --test src/charts/usageCharts.test.js`

- [ ] **Step 3: Commit:**
```bash
git add frontend/src/charts/usageCharts.js frontend/src/charts/usageCharts.test.js
git commit -m "feat(fe): pure usage gauge + per-model chart builders (TDD)"
```

---

### Task F4 — `EChart.vue` generic lazy-echarts component

**Files:** Create `frontend/src/charts/EChart.vue`.

- [ ] **Step 1: Implement** (mirrors JvChart.vue but takes a raw `option`; JvChart hardcodes `buildOption` and can't render a gauge):
```vue
<template>
  <div v-if="!option" class="jv-chart-bad">No data to display.</div>
  <div v-else ref="el" class="jv-echart"></div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from "vue"
const props = defineProps({ option: { type: Object, default: null } })
const el = ref(null)
let chart = null, ro = null

async function ensure() {
  if (!props.option || !el.value) return
  if (!chart) {
    const echarts = await import("echarts")
    if (!el.value) return
    chart = echarts.init(el.value, null, { renderer: "svg" })
    ro = new ResizeObserver(() => chart && chart.resize())
    ro.observe(el.value)
  }
  chart.setOption(props.option, true)
}
onMounted(() => nextTick(ensure))
watch(() => props.option, ensure)
onBeforeUnmount(() => {
  if (ro && el.value) ro.unobserve(el.value)
  if (chart) { chart.dispose(); chart = null }
})
</script>

<style scoped>
.jv-echart { width: 100%; height: 200px; }
.jv-chart-bad { font-size: 13px; color: var(--text-3); padding: 8px 0; }
</style>
```

- [ ] **Step 2: Verify build + Commit:** `npm run build` (echarts chunk emitted);
```bash
git add frontend/src/charts/EChart.vue && git commit -m "feat(fe): generic lazy EChart component"
```

---

### Task F5 — `MonitorTab.vue` admin-only Monitor tab

**Files:** Create `frontend/src/views/MonitorTab.vue`.

**Interfaces:** `<MonitorTab :dark="Boolean" />`. Consumes `getLlmConfig`, `getLlmUsage`, `getLlmConnectionStatus`, `getLlmSyncStatus`. Each fetch is independently try/caught (a `call` rejects on backend `frappe.throw`/PermissionError).

- [ ] **Step 1: Implement** (gauge reads `used_usd`/`limit_usd`; usage keyed on `applicable`):
```vue
<template>
  <div class="jv-mon">
    <div v-if="denied" class="jv-mon-empty">This view is available to System Managers only.</div>
    <template v-else>
      <section class="jv-mon-card">
        <h3>Status</h3>
        <div class="jv-mon-kv"><span>Mode</span><b>{{ config.proxy_active ? "Proxy" : "Direct" }}</b></div>
        <div class="jv-mon-kv"><span>Sync</span><b>{{ sync.last_sync_status || "—" }}</b></div>
        <div v-if="sync.last_sync_at" class="jv-mon-kv"><span>Last sync</span><b>{{ sync.last_sync_at }}</b></div>
      </section>

      <section class="jv-mon-card">
        <h3>Active pool</h3>
        <div class="jv-mon-kv"><span>Preset</span><b>{{ config.preset || "Custom" }}</b></div>
        <div class="jv-mon-kv"><span>Routing</span><b>{{ config.routing_mode || "failover" }}</b></div>
        <ol class="jv-mon-models">
          <li v-for="(m, i) in (config.models || [])" :key="i">
            {{ m.provider }} · {{ m.model }}
            <span class="jv-mon-tag">{{ i === 0 ? "runs every turn" : "backup" }}</span>
          </li>
        </ol>
      </section>

      <section class="jv-mon-card">
        <h3>Usage <span class="jv-mon-sub">· {{ usage.period || "current period" }}</span></h3>
        <div v-if="!usage.applicable" class="jv-mon-note">
          Usage is available on multi-model (proxy) setups. This tenant runs a single model (direct), so there is no proxy to meter.
        </div>
        <template v-else>
          <div class="jv-mon-stats">
            <div><span>Tokens in</span><b>{{ usage.tokens_in }}</b></div>
            <div><span>Tokens out</span><b>{{ usage.tokens_out }}</b></div>
            <div><span>Cost</span><b>${{ usage.cost_usd }}</b></div>
          </div>
          <JvChart v-if="perModelSpec" :spec="perModelSpec" :dark="dark" />
          <EChart v-if="gaugeOption" :option="gaugeOption" />
        </template>
      </section>

      <section class="jv-mon-card">
        <h3>Connection</h3>
        <div class="jv-mon-kv"><span>Auth</span><b>{{ conn.auth_present ? "Connected" : "Not connected" }}</b></div>
        <div v-if="conn.oauth_expires_at" class="jv-mon-kv"><span>Expires</span><b>{{ expiresLabel }}</b></div>
      </section>

      <section class="jv-mon-card jv-mon-soon">
        <h3>Request log &amp; failover history</h3>
        <div class="jv-mon-note">Coming soon.</div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue"
import JvChart from "@/charts/JvChart.vue"
import EChart from "@/charts/EChart.vue"
import { budgetGaugeOption, perModelBarSpec } from "@/charts/usageCharts.js"
import { getLlmConfig, getLlmUsage, getLlmConnectionStatus, getLlmSyncStatus } from "@/api"

const props = defineProps({ dark: { type: Boolean, default: false } })
const config = ref({ models: [], proxy_active: 0 })
const usage = ref({ applicable: false, per_model: [], used_vs_limit: {} })
const conn = ref({})
const sync = ref({})
const denied = ref(false)

const perModelSpec = computed(() =>
  (usage.value.per_model || []).length ? perModelBarSpec(usage.value.per_model, "tokens") : null)
const gaugeOption = computed(() => {
  const uv = usage.value.used_vs_limit || {}
  return budgetGaugeOption(uv.used_usd, uv.limit_usd, props.dark)
})
const expiresLabel = computed(() => {
  const ms = conn.value.oauth_expires_at
  return ms ? new Date(Number(ms)).toLocaleString() : "—"
})

async function load(fetchFn, target) {
  try { target.value = (await fetchFn()) || target.value }
  catch (e) { if (String(e && e.message).includes("PermissionError")) denied.value = true }
}
onMounted(async () => {
  await Promise.all([
    load(getLlmConfig, config), load(getLlmUsage, usage),
    load(getLlmConnectionStatus, conn), load(getLlmSyncStatus, sync),
  ])
})
</script>

<style scoped>
.jv-mon { display: grid; gap: 14px; }
.jv-mon-card { border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; background: var(--surface); }
.jv-mon-card h3 { font-size: 14px; font-weight: 600; margin: 0 0 10px; }
.jv-mon-sub, .jv-mon-tag { color: var(--text-3); font-weight: 450; font-size: 12px; }
.jv-mon-kv { display: flex; justify-content: space-between; font-size: 13px; padding: 4px 0; }
.jv-mon-models { margin: 6px 0 0; padding-left: 18px; font-size: 13px; }
.jv-mon-stats { display: flex; gap: 20px; margin-bottom: 10px; font-size: 13px; }
.jv-mon-note, .jv-mon-empty { font-size: 13px; color: var(--text-3); }
.jv-mon-empty { padding: 40px; text-align: center; }
</style>
```

- [ ] **Step 2: Verify build + Commit:** `npm run build` (exit 0);
```bash
git add frontend/src/views/MonitorTab.vue && git commit -m "feat(fe): admin-only Monitor tab"
```

---

### Task F6 — Mount MonitorTab into AiView (replace Plan 2 placeholder) + verify

**Files:** edit `frontend/src/views/AiView.vue`.

- [ ] **Step 1: Import + render** — replace the Monitor placeholder `<main v-show="activeTab==='monitor'">…</main>` block (from Plan 2 Task C4) with:
```vue
    <main v-show="activeTab==='monitor'" style="max-width:900px;margin:0 auto;padding:22px 18px;">
      <MonitorTab :dark="dark" />
    </main>
```
and add to `<script setup>`: `import MonitorTab from "@/views/MonitorTab.vue"`.

- [ ] **Step 2: Whole-plan frontend gate:** `cd frontend && node --test && npm run build` — all node:test suites (pool + theme + usageCharts) pass, build ok.

- [ ] **Step 3: Manual/e2e** at `/jarvis/ai` (Monitor tab) as System Manager, using the `verify`/`e2e-feature` skill:
  - PROXY tenant: status/active-pool cards populate; per-model bar + budget gauge render (toggle with dark mode); connection card shows auth/expiry.
  - DIRECT tenant (proxy_active=0): "Usage is available on multi-model (proxy) setups" note; usage/gauge hidden; "Coming soon" on the deferred panel.
  - Non-System-Manager: Monitor renders the "System Managers only" empty state (server 403 caught), no console throw.

- [ ] **Step 4: Commit** (jarvis repo):
```bash
git add frontend/src/views/AiView.vue && git commit -m "feat(fe): mount MonitorTab in /ai"
```

---

## Plan 3 Self-Review

- **Spec coverage:** L6 (admin-only, minimal REAL Bifrost metrics, proxy-only with DIRECT fallback), §5.2 (status/active-pool/usage/connection/deferred panels), §6.4 (read-back chain fleet→admin→customer), §7 (SM gate on customer wrappers), §10 (request-log/failover-history deferred "Coming soon"; live-read, no persistence). ✅
- **No placeholders:** all code present; Task D1 is a genuine spike with an explicit provisional-fallback so D2/D3 are runnable, flagged for live re-confirmation. ✅
- **Interface consistency:** `applicable` + `used_vs_limit:{used_usd,limit_usd}` used identically across fleet curate/route, admin passthrough, customer wrapper, and the frontend gauge; only `getLlmUsage`/`getLlmConnectionStatus` added to api.js (no re-declaration of Plan 2's wrappers); MonitorTab mounts into Plan 2's AiView placeholder. ✅
