import { test } from "node:test";
import assert from "node:assert/strict";
import { emptyStream, applyEvent } from "./chat_stream.mjs";

test("emptyStream: starts idle", () => {
  const s = emptyStream();
  assert.equal(s.live, null);
  assert.equal(s.busy, false);
  assert.equal(s.error, "");
  assert.deepEqual(s.pending, []);
  assert.equal(s.reload, false);
});

test("run:start opens a live turn and clears busy", () => {
  const s = applyEvent(
    { ...emptyStream(), busy: true },
    { kind: "run:start", run_id: "r1", message_id: "m1" }
  );
  assert.equal(s.busy, false);
  assert.deepEqual(s.live, { runId: "r1", messageId: "m1", text: "" });
});

test("assistant:delta ASSIGNS cumulative text, never appends", () => {
  let s = applyEvent(emptyStream(), { kind: "run:start", run_id: "r1", message_id: "m1" });
  s = applyEvent(s, { kind: "assistant:delta", run_id: "r1", text: "Hello" });
  s = applyEvent(s, { kind: "assistant:delta", run_id: "r1", text: "Hello there" });
  assert.equal(s.live.text, "Hello there");
});

test("assistant:delta with no prior run:start still opens a live turn", () => {
  const s = applyEvent(emptyStream(), { kind: "assistant:delta", run_id: "r1", text: "Hi" });
  assert.equal(s.live.text, "Hi");
  assert.equal(s.live.runId, "r1");
});

test("assistant:delta keeps a known message id when a later frame omits it", () => {
  let s = applyEvent(emptyStream(), { kind: "run:start", run_id: "r1", message_id: "m1" });
  s = applyEvent(s, { kind: "assistant:delta", run_id: "r1", text: "a" });
  assert.equal(s.live.messageId, "m1");
});

test("run:end clears live and asks for a reload", () => {
  let s = applyEvent(emptyStream(), { kind: "run:start", run_id: "r1" });
  s = applyEvent(s, { kind: "run:end", run_id: "r1" });
  assert.equal(s.live, null);
  assert.equal(s.busy, false);
  assert.equal(s.reload, true);
});

test("run:error surfaces the message and reloads", () => {
  const s = applyEvent(emptyStream(), { kind: "run:error", error: "The agent is unreachable." });
  assert.equal(s.error, "The agent is unreachable.");
  assert.equal(s.live, null);
  assert.equal(s.busy, false);
  assert.equal(s.reload, true);
});

test("run:error with no message falls back to a plain sentence", () => {
  const s = applyEvent(emptyStream(), { kind: "run:error" });
  assert.equal(s.error, "That turn failed.");
});

test("action:pending queues a confirmation, ignoring duplicate tokens", () => {
  let s = applyEvent(emptyStream(), {
    kind: "action:pending",
    token: "t1",
    tool: "create_doc",
    summary: "Create ToDo",
  });
  s = applyEvent(s, {
    kind: "action:pending",
    token: "t1",
    tool: "create_doc",
    summary: "Create ToDo",
  });
  assert.equal(s.pending.length, 1);
  assert.deepEqual(s.pending[0], { token: "t1", tool: "create_doc", summary: "Create ToDo" });
});

test("action:pending without a token is ignored", () => {
  const s = applyEvent(emptyStream(), { kind: "action:pending", summary: "no token" });
  assert.deepEqual(s.pending, []);
});

test("action:pending queues distinct tokens in arrival order", () => {
  let s = applyEvent(emptyStream(), { kind: "action:pending", token: "t1", summary: "first" });
  s = applyEvent(s, { kind: "action:pending", token: "t2", summary: "second" });
  assert.deepEqual(
    s.pending.map((p) => p.token),
    ["t1", "t2"]
  );
});

test("action:resolved drops the token", () => {
  let s = applyEvent(emptyStream(), { kind: "action:pending", token: "t1", summary: "x" });
  s = applyEvent(s, { kind: "action:resolved", token: "t1" });
  assert.deepEqual(s.pending, []);
});

test("conversation:renamed asks for a reload", () => {
  const s = applyEvent(emptyStream(), { kind: "conversation:renamed" });
  assert.equal(s.reload, true);
});

test("unknown kinds leave state untouched", () => {
  const before = emptyStream();
  const after = applyEvent(before, { kind: "something:new" });
  assert.deepEqual(after, before);
});

test("a missing or malformed payload is inert", () => {
  const before = emptyStream();
  assert.deepEqual(applyEvent(before, null), before);
  assert.deepEqual(applyEvent(before, undefined), before);
  assert.deepEqual(applyEvent(before, {}), before);
});

test("applyEvent does not mutate the input state", () => {
  const before = emptyStream();
  applyEvent(before, { kind: "run:start", run_id: "r1" });
  assert.equal(before.live, null);

  const withPending = applyEvent(before, { kind: "action:pending", token: "t1", summary: "x" });
  applyEvent(withPending, { kind: "action:resolved", token: "t1" });
  assert.equal(withPending.pending.length, 1);
});

test("live text survives an unrelated event", () => {
  let s = applyEvent(emptyStream(), { kind: "assistant:delta", run_id: "r1", text: "partial" });
  s = applyEvent(s, { kind: "action:pending", token: "t1", summary: "x" });
  assert.equal(s.live.text, "partial");
});
