import { test } from "node:test";
import assert from "node:assert/strict";
import { stripControlBlocks } from "./panel_markdown.mjs";

test("strips the jarvis-skill fence the agent appends to replies", () => {
  const src = "Here is the summary.\n\n```jarvis-skill\nerpnext-accounts\n```";
  assert.equal(stripControlBlocks(src), "Here is the summary.");
});

test("strips every control fence, keeping the prose", () => {
  for (const name of [
    "jarvis-action",
    "confirm",
    "jarvis-ask",
    "jarvis-cards",
    "jarvis-skill",
    "jarvis-macro",
    "jarvis-chart",
  ]) {
    const src = `Before.\n\n\`\`\`${name}\n{"x":1}\n\`\`\`\n\nAfter.`;
    const out = stripControlBlocks(src);
    assert.ok(!out.includes(name), `${name} leaked`);
    assert.ok(out.includes("Before.") && out.includes("After."));
  }
});

test("keeps ordinary code fences — those are content", () => {
  const src = "Run this:\n\n```bash\nbench migrate\n```";
  assert.ok(stripControlBlocks(src).includes("bench migrate"));
});

test("collapses the blank runs a stripped fence leaves behind", () => {
  const src = "A.\n\n```jarvis-skill\nx\n```\n\n\n\nB.";
  assert.equal(stripControlBlocks(src), "A.\n\nB.");
});

test("is safe on empty and non-string input", () => {
  assert.equal(stripControlBlocks(""), "");
  assert.equal(stripControlBlocks(null), "");
  assert.equal(stripControlBlocks(undefined), "");
});
