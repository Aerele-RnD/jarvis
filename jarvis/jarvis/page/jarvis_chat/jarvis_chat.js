frappe.pages["jarvis-chat"].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({
    parent: wrapper,
    title: "Jarvis Chat",
    single_column: true,
  });

  const root = $(page.body).addClass("jarvis-chat-page");
  root.html(`
    <div class="jarvis-chat-layout">
      <aside class="jarvis-chat-sidebar">
        <button class="btn btn-primary btn-sm jarvis-new-chat-btn">+ New Chat</button>
        <div class="jarvis-conversation-list"></div>
      </aside>
      <main class="jarvis-chat-main">
        <div class="jarvis-message-list"></div>
        <div class="jarvis-input-row">
          <textarea class="form-control jarvis-input" placeholder="Ask Jarvis a question…" rows="2"></textarea>
          <button class="btn btn-primary jarvis-send-btn">Send</button>
        </div>
      </main>
    </div>
  `);

  const state = {
    current_conversation: null,
  };

  const $list = root.find(".jarvis-message-list");
  const $sidebar = root.find(".jarvis-conversation-list");
  const $input = root.find(".jarvis-input");
  const $send = root.find(".jarvis-send-btn");
  const $newChat = root.find(".jarvis-new-chat-btn");

  // ---- Markdown rendering -----------------------------------------------

  function renderMarkdown(text) {
    // Prefer frappe.markdown if available (Desk's Showdown wrapper).
    // Otherwise fall back to text with newlines preserved.
    if (typeof frappe.markdown === "function") {
      try {
        return frappe.markdown(text || "");
      } catch (_) {
        // fall through
      }
    }
    const escaped = frappe.utils.escape_html(text || "");
    return escaped.replace(/\n/g, "<br>");
  }

  // ---- Sidebar -----------------------------------------------------------

  async function refreshSidebar() {
    const r = await frappe.call({ method: "jarvis.chat.api.list_conversations" });
    $sidebar.empty();
    (r.message || []).forEach((c) => {
      const $item = $(`
        <div class="jarvis-conv-item" data-name="${c.name}">
          ${frappe.utils.escape_html(c.title || "(untitled)")}
        </div>
      `);
      if (c.name === state.current_conversation) $item.addClass("active");
      $item.on("click", () => loadConversation(c.name));
      $sidebar.append($item);
    });
  }

  // ---- Conversation loading ---------------------------------------------

  async function loadConversation(name) {
    state.current_conversation = name;
    const r = await frappe.call({
      method: "jarvis.chat.api.get_conversation",
      args: { conversation: name },
    });
    $list.empty();
    (r.message.messages || []).forEach((msg) => $list.append(buildMessageEl(msg)));
    scrollToBottom();
    refreshSidebar();
  }

  // ---- Message rendering ------------------------------------------------

  function buildMessageEl(msg) {
    const $m = $(`<div class="jarvis-message ${msg.role}" data-msg="${msg.name}"></div>`);
    updateMessage($m, msg);
    return $m;
  }

  function updateMessage($el, msg) {
    if (msg.role === "tool") {
      const resultBlock = msg.tool_result
        ? `<pre>${frappe.utils.escape_html(
            typeof msg.tool_result === "string"
              ? msg.tool_result
              : JSON.stringify(msg.tool_result, null, 2),
          )}</pre>`
        : "";
      $el.html(`
        <div><strong>🔧 ${frappe.utils.escape_html(msg.tool_name || "")}</strong>
        — ${msg.tool_status || "running"}</div>
        ${resultBlock}
      `);
    } else if (msg.role === "assistant") {
      const html = renderMarkdown(msg.content || "");
      $el.html(html + (msg.streaming ? '<span class="jarvis-cursor">▍</span>' : ""));
    } else {
      $el.text(msg.content || "");
    }
  }

  function scrollToBottom() {
    if ($list[0]) $list.scrollTop($list[0].scrollHeight);
  }

  // ---- Sending ----------------------------------------------------------

  async function ensureConversation() {
    if (state.current_conversation) return state.current_conversation;
    const r = await frappe.call({ method: "jarvis.chat.api.create_conversation" });
    state.current_conversation = r.message;
    return r.message;
  }

  async function sendMessage() {
    const text = ($input.val() || "").trim();
    if (!text) return;
    const conv = await ensureConversation();
    $input.val("");
    $send.prop("disabled", true);
    const r = await frappe.call({
      method: "jarvis.chat.api.send_message",
      args: { conversation: conv, message: text },
    });
    $send.prop("disabled", false);
    if (!r.message.ok) {
      frappe.show_alert({ message: r.message.reason, indicator: "red" });
      return;
    }
    // Reload conversation to render the just-saved user message + placeholder
    await loadConversation(conv);
  }

  $send.on("click", sendMessage);
  $input.on("keypress", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  $newChat.on("click", async () => {
    const r = await frappe.call({ method: "jarvis.chat.api.create_conversation" });
    await loadConversation(r.message);
  });

  // ---- Realtime ---------------------------------------------------------

  frappe.realtime.on("jarvis:event", (payload) => {
    if (payload.conversation_id !== state.current_conversation) return;

    if (payload.kind === "run:start") {
      // Placeholder may not yet be in the DOM; reload to fetch it.
      loadConversation(state.current_conversation);
      return;
    }

    if (payload.kind === "assistant:delta") {
      const $el = $list.find(`[data-msg="${payload.message_id}"]`);
      if (!$el.length) return;
      updateMessage($el, {
        name: payload.message_id,
        role: "assistant",
        content: payload.text,
        streaming: true,
      });
      scrollToBottom();
      return;
    }

    if (payload.kind === "tool:start") {
      const $existing = $list.find(`[data-msg="${payload.message_id}"]`);
      if (!$existing.length) {
        $list.append(buildMessageEl({
          name: payload.message_id,
          role: "tool",
          tool_name: payload.tool_name,
          tool_status: "running",
        }));
      }
      scrollToBottom();
      return;
    }

    if (payload.kind === "tool:end") {
      const $el = $list.find(`[data-msg="${payload.message_id}"]`);
      if ($el.length) {
        updateMessage($el, {
          name: payload.message_id,
          role: "tool",
          tool_name: payload.tool_name,
          tool_status: payload.status || "completed",
        });
      }
      return;
    }

    if (payload.kind === "tool:result") {
      const $el = $list.find(`[data-msg="${payload.tool_message_id}"]`);
      if ($el.length) {
        updateMessage($el, {
          name: payload.tool_message_id,
          role: "tool",
          tool_name: payload.tool_name,
          tool_status: payload.status,
          tool_result: payload.result,
        });
      }
      return;
    }

    if (payload.kind === "run:end") {
      const $el = $list.find(`[data-msg="${payload.message_id}"]`);
      if ($el.length) $el.find(".jarvis-cursor").remove();
      return;
    }

    if (payload.kind === "run:error") {
      frappe.show_alert({
        message: `Run error: ${payload.error || "unknown"}`,
        indicator: "red",
      });
      return;
    }
  });

  // ---- Bootstrap --------------------------------------------------------

  refreshSidebar();
};
