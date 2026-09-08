import { test } from "node:test";
import assert from "node:assert/strict";
import { maintenanceActiveAfterSend } from "./panel_maintenance.mjs";

test("a maintenance refusal raises the banner", () => {
  assert.equal(
    maintenanceActiveAfterSend({ ok: false, reason: "maintenance" }),
    true
  );
});

test("a non-maintenance refusal leaves the banner unchanged (null)", () => {
  assert.equal(
    maintenanceActiveAfterSend({
      ok: false,
      reason: "release_update_required",
    }),
    null
  );
  assert.equal(
    maintenanceActiveAfterSend({ ok: false, reason: "usage_limit" }),
    null
  );
});

test("an accepted send clears the banner (proof the gate passed)", () => {
  assert.equal(maintenanceActiveAfterSend({ conversation_id: "c1" }), false);
  assert.equal(maintenanceActiveAfterSend({ ok: true }), false);
});

test("a confirmed parked card clears the banner — even a partial one (ok:false + confirmed)", () => {
  assert.equal(maintenanceActiveAfterSend({ confirmed: true }), false);
  // A partially-applied confirmation still got past validate_can_send, so the hold is
  // gone — this is the case Edge review #1 flagged as leaving a stale banner.
  assert.equal(
    maintenanceActiveAfterSend({ ok: false, confirmed: true }),
    false
  );
});

test("an empty/undefined response clears rather than sticking a stale hold", () => {
  assert.equal(maintenanceActiveAfterSend(undefined), false);
  assert.equal(maintenanceActiveAfterSend(null), false);
});
