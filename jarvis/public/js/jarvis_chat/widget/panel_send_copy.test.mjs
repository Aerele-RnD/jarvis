import { test } from "node:test";
import assert from "node:assert/strict";
import { sendRefusalMessage } from "./panel_send_copy.mjs";

test("sendRefusalMessage: release_update_required -> branded update line", () => {
  assert.equal(
    sendRefusalMessage("release_update_required", "Jarvis"),
    "A new Jarvis version is required. Please ask your administrator to update."
  );
});

test("sendRefusalMessage: the update line uses the passed (white-label) brand name", () => {
  // A customer who renamed the assistant must not see "Jarvis" leak.
  assert.equal(
    sendRefusalMessage("release_update_required", "Aida"),
    "A new Aida version is required. Please ask your administrator to update."
  );
});

test("sendRefusalMessage: a blank/missing brand falls back to 'Jarvis'", () => {
  const expected =
    "A new Jarvis version is required. Please ask your administrator to update.";
  assert.equal(sendRefusalMessage("release_update_required", ""), expected);
  assert.equal(sendRefusalMessage("release_update_required", "   "), expected);
  assert.equal(sendRefusalMessage("release_update_required"), expected);
});

test("sendRefusalMessage: any other refusal -> the generic try-again line", () => {
  assert.equal(
    sendRefusalMessage("something_else", "Aida"),
    "That couldn't be sent. Please try again."
  );
  // Brand is irrelevant to the generic line - it names no product.
  assert.equal(
    sendRefusalMessage("something_else"),
    "That couldn't be sent. Please try again."
  );
});

test("sendRefusalMessage: an unknown/empty reason -> the generic line, never branded", () => {
  const generic = "That couldn't be sent. Please try again.";
  assert.equal(sendRefusalMessage("", "Aida"), generic);
  assert.equal(sendRefusalMessage(undefined, "Aida"), generic);
  assert.equal(sendRefusalMessage(null, "Aida"), generic);
});
