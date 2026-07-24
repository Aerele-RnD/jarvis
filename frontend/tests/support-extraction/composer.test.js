// Task 4 of the PR1 extraction: the Composer generic core. Locks the rendered
// shape (snapshot) plus the four behaviours the host relies on — Send arming,
// the Send↔Stop swap, the "Uploading…" pill, and Enter vs Shift+Enter.
import { expect, test } from "vitest";
import { h } from "vue";
import Composer from "../../src/components/chat/Composer.vue";
import { mountWithPalette } from "./fixtures.js";

const findComposer = (w) => w.findComponent(Composer);

test("composer renders identically (light)", () => {
	const w = mountWithPalette(Composer, {
		modelValue: "hi",
		placeholder: "Ask Jarvis…",
		disclaimer: "Jarvis can make mistakes.",
	});
	expect(w.html()).toMatchSnapshot();
});

test("Send is armed once there is text", () => {
	const w = mountWithPalette(Composer, { modelValue: "hi" });
	const send = w.find(".jv-sendbtn");
	expect(send.exists()).toBe(true);
	expect(send.attributes("disabled")).toBeUndefined();
	expect(send.classes()).toContain("ready");
});

test("Send is disabled with an empty box and no attachments", () => {
	const w = mountWithPalette(Composer, { modelValue: "   " });
	const send = w.find(".jv-sendbtn");
	expect(send.attributes("disabled")).toBeDefined();
	expect(send.classes()).not.toContain("ready");
});

test("an attachment alone arms Send", () => {
	const w = mountWithPalette(Composer, {
		modelValue: "",
		attachments: [{ key: 0, file_name: "a.pdf", removable: true }],
	});
	expect(w.find(".jv-sendbtn").attributes("disabled")).toBeUndefined();
});

test("the canSend prop overrides the derived value", () => {
	const w = mountWithPalette(Composer, { modelValue: "hi", canSend: false });
	expect(w.find(".jv-sendbtn").attributes("disabled")).toBeDefined();
});

test("busy swaps Send for Stop and flips the hint", () => {
	const w = mountWithPalette(Composer, { modelValue: "hi", busy: true });
	expect(w.find(".jv-sendbtn").exists()).toBe(false);
	const stop = w.find('button[title="Stop generating"]');
	expect(stop.exists()).toBe(true);
	expect(w.text()).toContain("Stop");
	expect(w.text()).not.toContain("Enter ↵");
});

test("Stop emits stop", async () => {
	const w = mountWithPalette(Composer, { modelValue: "hi", busy: true });
	await w.find('button[title="Stop generating"]').trigger("click");
	expect(findComposer(w).emitted("stop")).toHaveLength(1);
});

test("an uploading attachment renders the Uploading… pill", () => {
	const w = mountWithPalette(Composer, {
		attachments: [{ key: "uploading", uploading: true }],
	});
	expect(w.text()).toContain("Uploading…");
});

test("attachments render an image thumbnail, a file chip, and remove buttons", async () => {
	const w = mountWithPalette(Composer, {
		attachments: [
			{ key: 0, file_name: "shot.png", preview_url: "/files/shot.png", removable: true },
			{ key: 1, file_name: "report.pdf", removable: false },
		],
	});
	const img = w.find("img");
	expect(img.attributes("src")).toBe("/files/shot.png");
	expect(w.text()).toContain("📎 report.pdf");
	// only the removable one gets an ×
	const removes = w.findAll("button").filter((b) => b.text() === "×");
	expect(removes).toHaveLength(1);
	await removes[0].trigger("click");
	expect(findComposer(w).emitted("remove-attachment")[0]).toEqual([0]);
});

test("Enter submits, Shift+Enter does not", async () => {
	const w = mountWithPalette(Composer, { modelValue: "hi" });
	const c = findComposer(w);
	const ta = w.find("textarea");
	await ta.trigger("keydown", { key: "Enter", shiftKey: true });
	expect(c.emitted("submit")).toBeUndefined();
	await ta.trigger("keydown", { key: "Enter" });
	expect(c.emitted("submit")).toHaveLength(1);
});

// The contract chat depends on: the raw keydown reaches the host BEFORE the
// built-in acts, so a host that claims the key (chat's mention navigation,
// prompt history and its own Enter-to-send all preventDefault) never gets a
// second, duplicate submit.
test("the raw keydown is emitted first, and a host preventDefault suppresses submit", async () => {
	const seen = [];
	const w = mountWithPalette(Composer, {
		modelValue: "hi",
		onKeydown: (e) => {
			seen.push(e.key);
			e.preventDefault();
		},
	});
	const c = findComposer(w);
	await w.find("textarea").trigger("keydown", { key: "Enter" });
	expect(seen).toEqual(["Enter"]);
	expect(c.emitted("submit")).toBeUndefined();
});

test("a host that does NOT preventDefault still gets the built-in submit", async () => {
	const w = mountWithPalette(Composer, { modelValue: "hi", onKeydown: () => {} });
	await w.find("textarea").trigger("keydown", { key: "Enter" });
	expect(findComposer(w).emitted("submit")).toHaveLength(1);
});

test("a host preventDefault on paste suppresses the built-in image extraction", async () => {
	const file = new File(["x"], "a.png", { type: "image/png" });
	const w = mountWithPalette(Composer, {
		modelValue: "",
		onPaste: (e) => e.preventDefault(),
	});
	await w.find("textarea").trigger("paste", { clipboardData: { files: [file], items: [] } });
	expect(findComposer(w).emitted("files-added")).toBeUndefined();
});

test("an unclaimed image paste emits files-added", async () => {
	const file = new File(["x"], "a.png", { type: "image/png" });
	const w = mountWithPalette(Composer, { modelValue: "" });
	await w.find("textarea").trigger("paste", { clipboardData: { files: [file], items: [] } });
	expect(findComposer(w).emitted("files-added")[0][0]).toEqual([file]);
});

test("typing emits update:modelValue then the raw input event", async () => {
	const w = mountWithPalette(Composer, { modelValue: "" });
	const c = findComposer(w);
	const ta = w.find("textarea");
	await ta.setValue("ab");
	expect(c.emitted("update:modelValue")[0]).toEqual(["ab"]);
	expect(c.emitted("input")).toHaveLength(1);
});

test("Send click emits submit", async () => {
	const w = mountWithPalette(Composer, { modelValue: "hi" });
	await w.find(".jv-sendbtn").trigger("click");
	expect(findComposer(w).emitted("submit")).toHaveLength(1);
});

test("drop emits files-added and never uploads", async () => {
	const w = mountWithPalette(Composer, { modelValue: "" });
	const c = findComposer(w);
	const file = new File(["x"], "a.png", { type: "image/png" });
	await w.find(".jv-composer").trigger("drop", { dataTransfer: { files: [file] } });
	expect(c.emitted("files-added")[0][0]).toEqual([file]);
});

test("the default #left-toolbar is an attach button; a host slot replaces it", () => {
	const plain = mountWithPalette(Composer, {});
	expect(plain.find('button[title="Attach file"]').exists()).toBe(true);
	// Chat takes the slot over (mic + its own 📎 + wiki) and drives the file
	// input through the `pickFiles` slot prop, so the default must yield.
	let slotProps = null;
	const slotted = mountWithPalette(
		Composer,
		{},
		{
			slots: {
				"left-toolbar": (p) => {
					slotProps = p;
					return h("button", { class: "host-mic" }, "mic");
				},
			},
		}
	);
	expect(slotted.find(".host-mic").exists()).toBe(true);
	expect(slotted.find('button[title="Attach file"]').exists()).toBe(false);
	expect(typeof slotProps.pickFiles).toBe("function");
});

test("the #above / #overlay / #footer slots render at their positions", () => {
	const w = mountWithPalette(
		Composer,
		{ disclaimer: "fine print" },
		{
			slots: {
				above: () => h("div", { class: "s-above" }, "nudge"),
				overlay: () => h("div", { class: "s-overlay" }, "mentions"),
				footer: () => h("div", { class: "s-footer" }, "foot"),
			},
		}
	);
	const html = w.html();
	expect(html.indexOf("s-above")).toBeLessThan(html.indexOf("jv-composer"));
	// the overlay sits inside the box, above the textarea
	expect(html.indexOf("s-overlay")).toBeLessThan(html.indexOf("<textarea"));
	expect(html.indexOf("fine print")).toBeLessThan(html.indexOf("s-footer"));
});

test("dark render", () => {
	const w = mountWithPalette(Composer, { modelValue: "hi" }, { dark: true });
	expect(w.html()).toMatchSnapshot();
});
