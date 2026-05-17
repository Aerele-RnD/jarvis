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
        <button class="btn btn-primary btn-sm jarvis-new-chat-btn">
          + New Chat
        </button>
        <div class="jarvis-conversation-list"></div>
      </aside>
      <main class="jarvis-chat-main">
        <div class="jarvis-message-list"></div>
        <div class="jarvis-input-row">
          <textarea
            class="form-control jarvis-input"
            placeholder="Ask Jarvis a question…"
            rows="2"
          ></textarea>
          <button class="btn btn-primary jarvis-send-btn">Send</button>
        </div>
      </main>
    </div>
  `);

  // Stub: real wiring is in the next task
  root.find(".jarvis-new-chat-btn").on("click", () => {
    frappe.msgprint("Chat backend wiring lands in the next task.");
  });
};
