// Pure decision for the desk widget's upgrade-maintenance banner state, extracted so the
// send() state machine is unit-tested — the widget SFC itself isn't, and the widget
// convention is to keep logic in a .mjs sibling (panel_readiness.mjs, panel_welcome.mjs,
// panel_size.mjs, …). Stream E.
//
// Given a send() response, return the next value for `maintenanceActive`:
//   - a "maintenance" refusal RAISES the banner (true).
//   - any response that got PAST the send gate — an accepted turn OR a confirmed parked
//     card (even a partially-applied one) — PROVES the hold has lifted, so it CLEARS
//     (false). Reaching either of those means validate_can_send passed, i.e. the mirror
//     is not held.
//   - a non-maintenance refusal leaves it unchanged (null → the caller keeps the current
//     state, e.g. a release-update or usage-limit refusal that has nothing to do with a
//     hold).
export function maintenanceActiveAfterSend(res) {
  if (res && res.ok === false && !res.confirmed) {
    return res.reason === "maintenance" ? true : null;
  }
  return false;
}

// The shared reactive state (maintenance_state.mjs) folds a send() response through this pure
// reducer, so the code that actually runs (foldSend) is the code under test. Returns the next
// {active}: a null from maintenanceActiveAfterSend (unrelated refusal) keeps the current state.
export function nextFromSend(state, res) {
  const next = maintenanceActiveAfterSend(res);
  return next === null ? { active: state.active } : { active: next };
}
