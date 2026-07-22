// Pure reducer over the `jarvis:event` realtime frames the chat worker
// publishes. Kept out of Panel.vue so the streaming rules — the easiest thing
// in this feature to get subtly wrong — are unit-testable without a browser.
//
// Reference implementation: pwa/src/views/ChatView.vue (onEvent).

export function emptyStream() {
  return { live: null, busy: false, error: "", pending: [], reload: false };
}

// Returns a NEW state; never mutates the input. The caller assigns the result
// to a Vue ref, so structural sharing is not worth the aliasing risk.
export function applyEvent(state, payload) {
  const p = payload || {};
  const s = {
    live: state.live ? { ...state.live } : null,
    busy: state.busy,
    error: state.error,
    pending: state.pending.slice(),
    reload: state.reload,
  };

  switch (p.kind) {
    case "run:start":
      s.busy = false;
      s.live = { runId: p.run_id || "", messageId: p.message_id || "", text: "" };
      return s;

    case "assistant:delta":
      // The frame carries the FULL text so far, not an increment. Assign it —
      // appending doubles the reply.
      if (!s.live) s.live = { runId: p.run_id || "", messageId: "", text: "" };
      s.live.messageId = p.message_id || s.live.messageId;
      s.live.text = p.text || "";
      return s;

    case "run:end":
      s.busy = false;
      s.live = null;
      // The reply is durable now; re-fetch rather than trusting the streamed
      // copy, which lacks the final formatting.
      s.reload = true;
      return s;

    case "run:error":
      s.busy = false;
      s.live = null;
      s.error = p.error || "That turn failed.";
      s.reload = true;
      return s;

    case "action:pending":
      // The agent is blocked waiting on a write confirmation. Without this the
      // panel would sit on "Jarvis is replying..." forever.
      if (!p.token) return s;
      if (s.pending.some((x) => x.token === p.token)) return s;
      s.pending.push({ token: p.token, tool: p.tool || "", summary: p.summary || "" });
      return s;

    case "action:resolved":
      s.pending = s.pending.filter((x) => x.token !== p.token);
      return s;

    case "conversation:renamed":
      s.reload = true;
      return s;

    default:
      return s;
  }
}
