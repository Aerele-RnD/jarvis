import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PANEL_W,
  PANEL_MAX_H,
  GAP,
  MARGIN,
  panelLayout,
} from "./panel_anchor.mjs";

// A roomy desktop viewport with a 48px Desk navbar.
const VP = { vw: 1440, vh: 900, top: 48 };
const FAB = 54;

test("docked right: the panel opens to the LEFT of the FAB", () => {
  const fab = { x: 1440 - 54 - 16, y: 700, size: FAB };
  const l = panelLayout(fab, VP);
  assert.equal(l.side, "left");
  assert.equal(l.left, fab.x - GAP - PANEL_W);
  assert.equal(l.width, PANEL_W);
});

test("docked left: the panel opens to the RIGHT of the FAB", () => {
  const fab = { x: 16, y: 700, size: FAB };
  const l = panelLayout(fab, VP);
  assert.equal(l.side, "right");
  assert.equal(l.left, fab.x + FAB + GAP);
});

test("the panel's bottom aligns with the FAB's bottom", () => {
  const fab = { x: 1370, y: 700, size: FAB };
  const l = panelLayout(fab, VP);
  assert.equal(l.top + l.height, fab.y + FAB);
});

// The FAB is draggable anywhere down the edge, so a naive bottom-align would
// push the panel off-screen at the extremes. These two are the whole point of
// the "user moved the icon" requirement.
test("FAB dragged to the very top: the panel clamps below the navbar", () => {
  const fab = { x: 1370, y: 52, size: FAB };
  const l = panelLayout(fab, VP);
  assert.equal(l.top, VP.top + MARGIN);
  assert.ok(l.top + l.height <= VP.vh - MARGIN);
});

test("FAB dragged to the very bottom: the panel stays inside the viewport", () => {
  const fab = { x: 1370, y: 880, size: FAB };
  const l = panelLayout(fab, VP);
  assert.ok(l.top + l.height <= VP.vh - MARGIN, "bottom must not overflow");
  assert.ok(l.top >= VP.top + MARGIN, "top must clear the navbar");
});

test("height is capped at the mini-chat size, not stretched to the viewport", () => {
  const l = panelLayout({ x: 1370, y: 700, size: FAB }, VP);
  assert.equal(l.height, PANEL_MAX_H);
  assert.ok(l.height < VP.vh - VP.top, "a mini chat never fills the page");
});

test("a short viewport shrinks the panel instead of overflowing", () => {
  const vp = { vw: 1280, vh: 500, top: 48 };
  const l = panelLayout({ x: 1200, y: 400, size: FAB }, vp);
  assert.equal(l.height, vp.vh - vp.top - MARGIN * 2);
  assert.ok(l.top >= vp.top + MARGIN);
  assert.ok(l.top + l.height <= vp.vh - MARGIN);
});

test("a narrow viewport shrinks the width and keeps both margins", () => {
  const vp = { vw: 380, vh: 800, top: 48 };
  const l = panelLayout({ x: 320, y: 600, size: FAB }, vp);
  assert.equal(l.width, vp.vw - MARGIN * 2);
  assert.ok(l.left >= MARGIN);
  assert.ok(l.left + l.width <= vp.vw - MARGIN);
});

test("no room on the preferred side: the panel flips rather than overflowing", () => {
  // FAB dragged to the left edge, but the panel cannot fit to its right.
  const vp = { vw: 520, vh: 900, top: 48 };
  const l = panelLayout({ x: 12, y: 700, size: FAB }, vp);
  assert.ok(l.left >= MARGIN, "never off the left edge");
  assert.ok(l.left + l.width <= vp.vw - MARGIN, "never off the right edge");
});

test("layout is a pure function of its inputs", () => {
  const fab = { x: 1370, y: 700, size: FAB };
  assert.deepEqual(panelLayout(fab, VP), panelLayout(fab, VP));
});

test("junk input yields a usable layout rather than NaN", () => {
  const l = panelLayout(null, VP);
  assert.ok(Number.isFinite(l.left) && Number.isFinite(l.top));
  assert.ok(Number.isFinite(l.width) && Number.isFinite(l.height));
});
