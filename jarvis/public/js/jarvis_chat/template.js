// HTML template for the page shell. Empty states live here too so the
// initial paint shows something other than a blank page.

export const PAGE_HTML = `
<div class="jarvis-chat-layout">
  <aside class="jarvis-chat-sidebar">
    <div class="jarvis-sidebar-header">
      <div class="jarvis-sidebar-title">Conversations</div>
    </div>
    <div class="jarvis-conversation-list"></div>
    <div class="jarvis-sidebar-empty" hidden>
      <div class="jarvis-sidebar-empty-text">No chats yet.</div>
      <div class="jarvis-sidebar-empty-hint">Click <b>+ New Chat</b> in the header to begin.</div>
    </div>
  </aside>

  <main class="jarvis-chat-main">
    <div class="jarvis-message-list">
      <div class="jarvis-welcome">
        <div class="jarvis-welcome-icon">✦</div>
        <h3>Talk to Jarvis</h3>
        <p>Ask about your data, run reports, or summarize a doc. Jarvis sees only
           what you can see in this site.</p>
        <div class="jarvis-welcome-examples">
          <button class="jarvis-example" data-prompt="List 5 customers">List 5 customers</button>
          <button class="jarvis-example" data-prompt="Show me last week's sales orders">Show me last week's sales orders</button>
          <button class="jarvis-example" data-prompt="Summarize the latest task assigned to me">Summarize the latest task assigned to me</button>
        </div>
      </div>
    </div>

    <div class="jarvis-thinking" hidden>
      <span class="jarvis-thinking-dot"></span>
      <span class="jarvis-thinking-dot"></span>
      <span class="jarvis-thinking-dot"></span>
      <span class="jarvis-thinking-text">Jarvis is thinking…</span>
    </div>

    <div class="jarvis-input-row">
      <textarea class="form-control jarvis-input" rows="1"
                placeholder="Ask Jarvis anything…"></textarea>
      <button class="btn btn-primary jarvis-send-btn" disabled>
        <span class="jarvis-send-label">Send</span>
        <span class="jarvis-send-spinner" hidden>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
               class="jarvis-spin">
            <line x1="12" y1="2" x2="12" y2="6"></line>
            <line x1="12" y1="18" x2="12" y2="22"></line>
            <line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line>
            <line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line>
            <line x1="2" y1="12" x2="6" y2="12"></line>
            <line x1="18" y1="12" x2="22" y2="12"></line>
            <line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line>
            <line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line>
          </svg>
        </span>
      </button>
    </div>
    <div class="jarvis-input-hint">
      <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> for newline
    </div>
  </main>
</div>
`;
