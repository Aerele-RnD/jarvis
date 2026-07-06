# Research: Jarvis Vue SPA — Mobile Wrapping Evaluation

> Supporting research for the Jarvis mobile app design (see `2026-07-06-mobile-backend-design.md`). Produced 2026-07-06 by a read-only codebase-exploration agent against `/Users/kavin/frappe/v16/bench-16/apps/jarvis` (feat/llm-proxy-ui working tree). Question answered: could the existing Vue 3 chat SPA be wrapped with Capacitor, versus building a new native client that reuses its HTTP/realtime API?

App root: `/Users/kavin/frappe/v16/bench-16/apps/jarvis` — a standard Frappe app with a Vite/Vue 3 SPA in `frontend/`, built into `jarvis/public/frontend/` and served as a Frappe website page at `/jarvis`.

## 1. SPA structure

- **Location**: `frontend/` (Vite project). Entry `frontend/src/main.js`; root `frontend/src/App.vue`. Build output goes to `jarvis/public/frontend/` and injects the HTML shell at `jarvis/www/jarvis.html` (see `frontend/vite.config.js:1` — uses `frappe-ui/vite` plugin with `frontendRoute: "/jarvis"`).
- **Served by**: `jarvis/www/jarvis.py` (a Frappe www page). `get_context` emits a `boot` dict → `window.csrf_token`, `window.site_name`, `window.default_route`, `window.time_zone` into `jarvis.html`. `no_cache = 1`. Routing to `/jarvis` is a website route rule / catch-all (referenced in `frontend/src/router/index.js:72`).
- **Router** (`frontend/src/router/index.js`): `createWebHistory("/jarvis")`. Routes: `/` and `/c/:id` → `ChatView` (chat is home, statically imported); `/skills`, `/skills/new`, `/skills/:id`, `/macros*`, `/files`, `/approvals`, `/approvals/:id`, `/agents`, `/agents/:slug` — all lazy-loaded. Plus legacy hash deep-links (`#skills` → `/skills`, etc., `index.js:81`).
- **Main views/components**:
  - Chat: `frontend/src/views/ChatView.vue` — **4,042 LOC monolith** (composer, thread, streaming, canvas, settings, notifications, file upload, confirmations, macro banners all inline).
  - Shell: `frontend/src/components/shell/` — `AppShell.vue`, `Sidebar.vue` (conversation list + nav), `ConversationRow.vue`, `UserMenu.vue`, `JarvisCommandPalette.vue` (⌘K).
  - Feature pages: `frontend/src/pages/{agents,macros,files,skills,approvals}/`.
  - Canvas/charts: rendered **inline inside ChatView** via `getCanvas()` into a sandboxed `<iframe srcdoc>`; charts via `frontend/src/charts/JvChart.vue` (echarts) + `mermaid`. No separate Canvas or Settings route — settings live inside ChatView.
- **State management**: no Vuex/Pinia. A hand-rolled reactive store `frontend/src/stores/shell.js` (188 LOC, `reactive`/`ref`/`computed`, `@vueuse/core` `useStorage`). ChatView keeps most chat state locally and is documented as "the ONLY external writer" of streaming state (`shell.js:7`, `:145`).
- **frappe-ui usage**: `frappe-ui@0.1.278`. `main.js` uses `setConfig`, `frappeRequest`, `resourcesPlugin`. All API calls go through frappe-ui's `call()` (`frontend/src/api.js:4`). Tailwind 3 + frappe-ui preset.

## 2. API surface a mobile client would use

Backend whitelisted endpoints total ~150 across the app; the chat-relevant ones are in `jarvis/chat/api.py` and sibling `*_api.py`. SPA wrappers are all in `frontend/src/api.js`. Key ones:

- `send_message(conversation?, message, model_override?, attachments?, context?, thinking_override?)` (`api.py:381`). `conversation` empty ⇒ server creates/focuses an empty one. `attachments` = JSON list of `{file_url,file_name}` (pre-uploaded). Returns `{ok, run_id, message_id, conversation_id}` or `{ok:False, reason}`. **Async by design** — the actual reply streams over the socket, not in this response.
- `list_conversations()` → array of `{name,title,last_active_at,starred,message_count}` (`api.py:62`). `search_conversations()` → `{rows,total,has_more,start,page_length}` (`api.py:90`).
- `get_conversation(conversation)` → `{conversation:{name,title,status,session_key,model_override,auto_apply,last_active_at}, messages:[{name,seq,role,content,streaming,error,tool_name,tool_args,tool_result,tool_status,canvas,creation,modified}]}` (`api.py:164`). `canvas` parsed to a list.
- `retry_message(message)` → re-runs the errored turn, `{ok, run_id}` (`api.py:769`).
- `get_canvas(message,name,dark)` (`api.py:204`, HTML/SVG/pdf/image for iframe/img), `preview_file`, `create_or_focus_empty`, `archive_conversation`, `clear_chat_history`, `rename_conversation`, `set_star`, `set_auto_apply`, `get_usage`, `set_conversation_model`, `get_chat_ui_settings`, `warm_session`, `set_conversation_thinking`, `get_doctype_fields`.
- Feature namespaces (all `call()`-based): `custom_skills_api.*`, `macros_api.*`, `actions_api.*` (record-draft apply + `confirm_tool` write-safety gate + `list_pending_confirmations`), `filebox.*`, `approvals_api.*`, `agents_api.*`. Uploads via raw `fetch("/api/method/upload_file")` (`api.js:116`). Mentions reuse `frappe.desk.search.search_link`.

**Auth**: pure **Frappe session cookie** — same as Desk. No token flow. `main.js:14` `requireLogin()` reads the `user_id` cookie (`frontend/src/data/session.js`) and bounces to `/login?redirect-to=...` if Guest. **CSRF**: `window.csrf_token` from boot; frappe-ui's `call`/`frappeRequest` sends it as `X-Frappe-CSRF-Token`; the manual upload sets the same header explicitly (`api.js:122`). For a native client this means authenticating to get a session (or switching to OAuth — see §7) and sending the CSRF header on writes.

## 3. Realtime

- **Transport**: the same **Frappe socket.io server** the Desk uses. `frontend/src/socket.js` — `socket.io-client@4.7.5`, connects to `http(s)://host[:socketio_port]/<siteName>` with `withCredentials:true` (session cookie authenticates + joins the user's room). `socketio_port` read from `sites/common_site_config.json`. `?nosocket` query disables it (`main.js:24`).
- **Channel**: a single event name `"jarvis:event"` (`jarvis/chat/events.py:19`, `CHANNEL`). Backend publishes via `frappe.publish_realtime("jarvis:event", payload, user=user)` (`events.py:65` `publish_to_user`) — **user-scoped rooms**, not conversation rooms.
- **Event kinds** consumed in `ChatView.onEvent` (`ChatView.vue:2912`): `run:start`, `assistant:delta` (`p.text` = cumulative; upserts the streaming message), `tool:start`/`tool:end` (with `tool_title`), `canvas`, `run:end` (stamps metrics, fires opt-in notification, **then refetches**), `run:error`; plus out-of-band `conversation:renamed`, `conversation:new` (proactive), `macro:progress`/`macro:done`, `action:pending` (write-safety card). Events are guarded by `p.conversation_id === currentId` and `stoppedRunId`.
- **Reconnect/catch-up**: **socket.io has no replay** — the SPA does not trust the stream across gaps. On every `connect` and on tab-visible it runs `onResync` (`ChatView.vue:3266`) → `loadConversations()` + `loadConversation(currentId)` (debounced 2s). Also, `run:end` itself calls `loadConversation` to reconcile from durable DB state (`ChatView.vue:3056`). This "refetch on reconnect" pattern is exactly what a native client should replicate. Note `stopRun()` is UI-only — **there is no server-side cancel endpoint** (`ChatView.vue:3076`).

## 4. Mobile-readiness of the UI — the main concern

The UI is **desktop-first and effectively not responsive**:

- **Only one `@media` query in the entire SPA**: `ChatView.vue:3997` (`max-width:700px` for draft-field grid). Only **12 total** Tailwind responsive (`sm:`/`md:`/`lg:`) class occurrences across all of `src/`, in 5 non-chat files. ChatView uses heavy inline `style="..."` with fixed px, not responsive utilities.
- **Sidebar**: `stores/shell.js:35` auto-collapses at `≤820px` to a **48px icon rail** (`Sidebar.vue:4` `w-12`), not an off-canvas drawer/hamburger. No phone-oriented navigation pattern.
- **Viewport**: `jarvis.html` has `<meta name="viewport" content="width=device-width, initial-scale=1.0">` and a pre-boot dark-theme flash guard. No `viewport-fit=cover`, no safe-area insets (notch/home-indicator not handled).
- **Desktop-only interactions**: keyboard shortcuts everywhere (`composables/useShortcuts.js`, ⌘K palette, Ctrl+B collapse, Ctrl+Shift+O new chat); drag-and-drop file upload (`ChatView.vue:359`, `FilesList.vue`, `StepsBuilder.vue` reorder); pointerdown-based dismiss menus; hover affordances.
- **PWA**: **none** — no manifest, no service worker, no `registerSW` anywhere.

Implication: a Capacitor wrap would render the desktop layout shrunk on a phone. Substantial responsive CSS work (a real mobile chat layout, drawer nav, safe-area handling, touch targets) would be needed before wrapping is acceptable — and most of that work concentrates in the 4,042-line `ChatView.vue`.

## 5. Voice / attachments

- **Voice**: **none**. No `MediaRecorder`, `SpeechRecognition`, `getUserMedia`, or audio capture anywhere in `src/`. Net-new for a mobile client.
- **Attachments**: solid and reusable. `uploadFile()` → `POST /api/method/upload_file` (private File doctype), returns `{file_url,file_name}` (`api.js:116`). ChatView supports file-picker, clipboard **paste**, and **drag-drop** upload (`ChatView.vue:3094-3184`); image attachments are stored as canvas items and shown inline. Also a File Box drop flow (`filebox.drop_file`). Native clients can hit `upload_file` directly (multipart + CSRF header) then pass `attachments` JSON to `send_message`.

## 6. Notifications

- **Browser Notification API only**, opt-in and desktop-oriented (`ChatView.vue:1234-1262`): `toggleNotify()` calls `Notification.requestPermission()`, and `_notifyReplyReady()` fires `new Notification("Jarvis replied", …)` only when `document.hidden`, on `run:end`. Persisted per-device in localStorage.
- **Backend push** is `frappe.publish_realtime` (socket only) — see §3. There's a `proactive` path (`jarvis/chat/proactive.py`, `conversation:new` event) but no web-push, FCM/APNs, or email notification for chat replies. A mobile app needing background/push notifications requires new server work (native push tokens + a publish hook).

## 7. OAuth provider (for native-client auth)

Two distinct things — don't conflate:

- **Frappe's OAuth2 server IS available on this bench** (usable for a native client to obtain tokens instead of cookies): `/Users/kavin/frappe/v16/bench-16/apps/frappe/frappe/integrations/oauth2.py` exists (16 KB). It supports:
  - **PKCE with S256** (`oauth2.py:326` `code_challenge_methods_supported=["S256"]`).
  - **Public clients** (`oauth2.py:320` `token_endpoint_auth_methods_supported=["none","client_secret_basic"]`; `:404` `doc.is_public_client()`) — i.e. no client secret, PKCE-only, exactly the mobile/SPA pattern.
  - OIDC discovery metadata and **dynamic client registration** for public clients (`oauth2.py:507`, `:547` `allowed_public_client_origins`).
  - **OAuth Client doctype** at `apps/frappe/frappe/integrations/doctype/oauth_client/` — fields include `client_id`, `client_secret`, `redirect_uris`, `default_redirect_uri`, `grant_type`, `response_type`, `scopes`, `skip_authorization`, `allowed_roles`, and `token_endpoint_auth_method` (its `"None"` value = public client, PKCE token exchange — `oauth_client.json:195`). A native app can register a public PKCE client and use Authorization Code + PKCE.
- **Jarvis's own `jarvis/oauth/`** is unrelated to app auth — it's the customer bench signing **into LLM providers** (OpenAI/Gemini/Claude) via a paste-based PKCE flow (`jarvis/oauth/api.py:107` `_generate_pkce`, `begin_paste_signin`/`complete_paste_signin`). Not relevant to authenticating a mobile client to Jarvis, but confirms the team already understands PKCE.

## 8. Size & code smells that make wrapping painful

- **SPA size**: ~**14,520 LOC** across ~60 files in `frontend/src/`. Deps: Vue 3.4, vue-router 4, frappe-ui 0.1.278, socket.io-client 4.7, echarts, mermaid, dompurify, @vueuse/core.
- **Biggest smell**: `ChatView.vue` is a **4,042-line monolith** holding composer, streaming state machine, socket handlers, canvas rendering, settings, notifications, upload, confirmations, and macro banners. Any mobile refactor touches this one file. Next largest: `LearningTab.vue` (1,290), `AgentDetail.vue` (848).
- **Hard-coupled to Frappe web context**: session-cookie auth + `window.csrf_token` from server-rendered boot (`jarvis.html`), socket URL derived from `common_site_config.json` and `window.site_name`, base path hard-wired to `/jarvis`. Under Capacitor (served from `capacitor://`/`file://`) none of these are present: no boot script injects `csrf_token`/`site_name`, cookies/CSRF and CORS/`withCredentials` all break. A token-based auth shim (frappe OAuth2/PKCE from §7), an absolute API base URL, and a socket URL override would be needed.
- **No server-side run cancel**, **no reconnect replay** (client compensates by refetching — fine, but a native client must do the same), **no PWA/offline**, **no responsive layout**, **no voice**, **no push**.

## Bottom line

Wrapping the existing Vue SPA with Capacitor is technically possible but **not cheap**: the app is desktop-first (1 media query, no drawer nav, no safe-area/touch design, heavy keyboard/hover/drag interactions) and hard-wired to Frappe's cookie+CSRF+boot+socket web context. The investment would go to (a) responsivizing a 4k-line `ChatView.vue`, and (b) a token-auth + absolute-URL shim to make it run outside a Frappe-served page. The **API/realtime surface itself is clean and reusable** for a native client (well-defined `call()` endpoints in `frontend/src/api.js`, a single `jarvis:event` socket channel with a documented refetch-on-reconnect model, existing `upload_file`, and frappe's PKCE public-client OAuth2 already on the bench) — so building a new native client against the HTTP/realtime API avoids the desktop-CSS and web-context debt while reusing the entire backend. Voice input and push notifications are net-new either way.
