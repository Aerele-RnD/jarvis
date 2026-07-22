// Agent replies are GFM: bold, bullets, pipe tables, fenced code. Rendering
// them as plain text is how the panel ended up showing literal ** and | rows.
//
// The renderer is the SPA's own (frontend/src/markdown.js) rather than a third
// implementation — it is dependency-free and already tuned for these replies,
// and it escapes HTML before emitting, which is what makes v-html safe here.
import { renderMarkdown } from "../../../../../frontend/src/markdown.js";

// Control fences the agent uses to talk to the UI, not to the reader. The full
// SPA turns several of these into cards; this panel is text-only, so strip them
// all rather than print their JSON. Mirrors ChatView's _stripControlBlocks.
const CONTROL_FENCES = [
  "jarvis-action",
  "confirm",
  "jarvis-ask",
  "jarvis-cards",
  "jarvis-skill",
  "jarvis-macro",
  "jarvis-chart",
];

export function stripControlBlocks(src) {
  let t = String(src == null ? "" : src);
  for (const name of CONTROL_FENCES) {
    t = t.replace(new RegExp("```" + name + "[ \\t]*\\n[\\s\\S]*?```", "g"), "");
  }
  t = t.replace(/```mermaid[ \t]*\n[ \t]*xychart-beta[\s\S]*?```/g, "");
  return t.replace(/\n{3,}/g, "\n\n").trim();
}

export function renderReply(src) {
  return renderMarkdown(stripControlBlocks(src));
}
