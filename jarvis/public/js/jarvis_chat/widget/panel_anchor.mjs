// Where the mini chat window sits relative to the FAB.
//
// The FAB is draggable to any point down either edge, so the panel cannot have
// a fixed home: it opens beside wherever the launcher currently is, flips to
// the other side when there is no room, and clamps so it never leaves the
// viewport or slides under the Desk navbar. Pure geometry, like
// fab_position.mjs, so every edge case is a unit test instead of a drag
// session in a browser.

// Normal mini-chat proportions (Intercom/Crisp class), not a full-height dock:
// the panel is a window over the page, not a second column of it.
export const PANEL_W = 400;
export const PANEL_MAX_H = 600;
export const GAP = 12; // between the FAB and the panel
export const MARGIN = 12; // minimum clearance from every viewport edge

function clamp(n, lo, hi) {
  if (hi < lo) return lo;
  return Math.min(hi, Math.max(lo, n));
}

// fab: { x, y, size } — the FAB's top-left in viewport coordinates.
// vp:  { vw, vh, top } — top is the Desk navbar height the panel must clear.
// Returns { left, top, width, height, side }, all in viewport pixels.
export function panelLayout(fab, vp) {
  const v = vp || {};
  const vw = Number.isFinite(v.vw) ? v.vw : 1024;
  const vh = Number.isFinite(v.vh) ? v.vh : 768;
  const top = Number.isFinite(v.top) ? v.top : 0;

  const f = fab || {};
  const size = Number.isFinite(f.size) ? f.size : 54;
  const fx = Number.isFinite(f.x) ? f.x : vw - size - MARGIN;
  const fy = Number.isFinite(f.y) ? f.y : vh - size - MARGIN;

  const width = Math.min(PANEL_W, Math.max(0, vw - MARGIN * 2));
  const height = Math.min(PANEL_MAX_H, Math.max(0, vh - top - MARGIN * 2));

  // Prefer the side facing into the page: a right-docked FAB opens leftward.
  const fabCentre = fx + size / 2;
  const preferLeft = fabCentre > vw / 2;

  const leftOption = fx - GAP - width; // panel sits left of the FAB
  const rightOption = fx + size + GAP; // panel sits right of the FAB

  let side;
  let left;
  if (preferLeft) {
    side = "left";
    left = leftOption;
    if (left < MARGIN && rightOption + width <= vw - MARGIN) {
      side = "right";
      left = rightOption;
    }
  } else {
    side = "right";
    left = rightOption;
    if (left + width > vw - MARGIN && leftOption >= MARGIN) {
      side = "left";
      left = leftOption;
    }
  }
  // Neither side fits (a viewport barely wider than the panel): clamp.
  left = clamp(left, MARGIN, vw - MARGIN - width);

  // Bottom-align with the FAB so the panel grows upward out of the launcher,
  // then clamp into the band between the navbar and the viewport floor.
  const bottomAligned = fy + size - height;
  const topPos = clamp(bottomAligned, top + MARGIN, vh - MARGIN - height);

  return { left, top: topPos, width, height, side };
}
