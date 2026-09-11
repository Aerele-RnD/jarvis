// Shared reactive upgrade-maintenance state for the Desk widget (Stream E, review finding #5).
// Both the FAB (Widget.vue, always mounted) and the chat Panel (lazily mounted on first open)
// import this ONE singleton, so they can never disagree on hold state. A 60s poll — armed at
// module load if the boot state is held, and on every transition-into-held — lifts the banner
// when the operator/roll clears the hold, so an idle bubble self-heals without a Desk reload.
//
// The pure decision (nextFromSend) lives in panel_maintenance.mjs so `node --test` can exercise
// it without a bundler; this module holds only the reactive wrapper + poll (vue + the Desk
// `frappe.call` global), which the flow review exercises in the browser.
import { reactive } from "vue";
import { nextFromSend } from "./panel_maintenance.mjs";

const _boot =
  (typeof window !== "undefined" && window.frappe?.boot?.jarvis_maintenance) ||
  {};
export const maintenance = reactive({
  active: !!_boot.active,
  message: (_boot.message || "").trim(),
});

let _timer = null;

export function startPollIfHeld() {
  // Poll only WHILE held (bounded work), coalesced by check()'s own 30s server-side cache.
  if (!_timer && maintenance.active) {
    _timer = setInterval(recheck, 60000);
  }
}

export function stopPoll() {
  if (_timer) {
    clearInterval(_timer);
    _timer = null;
  }
}

// Fold a send() response into the shared state and re-sync the poll: a raised hold ARMS the
// poll (so the tab that raised it still self-heals when idle), an accepted send stops it.
export function foldSend(res) {
  maintenance.active = nextFromSend(maintenance, res).active;
  if (maintenance.active) {
    startPollIfHeld();
  } else {
    stopPoll();
  }
}

let _rechecking = false;

// Re-pull the mirror from admin (jarvis.maintenance_notice.check) and fold it in. Keeps
// last-known on any error or malformed shape (never clears a live hold on a flaky poll), and
// never reloads the page.
export async function recheck() {
  if (_rechecking) {
    return;
  }
  _rechecking = true;
  try {
    const r = await frappe.call({ method: "jarvis.maintenance_notice.check" });
    const m = r && r.message;
    if (m && typeof m === "object" && "active" in m) {
      maintenance.active = !!m.active;
      maintenance.message = (m.message || "").trim();
    }
  } catch (_e) {
    // keep last-known
  } finally {
    _rechecking = false;
  }
  if (maintenance.active) {
    startPollIfHeld();
  } else {
    stopPoll();
  }
}

// Self-arm at module load so an idle FAB (panel never opened) still self-heals: this module is
// imported by the always-mounted Widget, so this side-effect runs on every Desk page.
startPollIfHeld();
