# UI/UX design prompt — Jarvis mobile app

> **How to use:** paste everything below the line into a Claude design session. It is fully self-contained — no repo access needed. Written 2026-07-06, matched to the v1 backend design (`2026-07-06-mobile-backend-design.md`).

---

# Design brief: "Jarvis" mobile app (iOS + Android) — B2B AI agent for ERP

## What Jarvis is

Jarvis is a SaaS product where each business customer gets an AI agent that operates their ERP system (Frappe/ERPNext: invoices, orders, stock, accounting) through natural-language chat. Users are business owners, accountants, and operations staff. The web app exists; this is the FIRST mobile app. Its job: let users stay connected to their AI agent when away from the desk — get notified when long tasks finish, approve/deny the agent's proposed ERP changes, and fire off new requests from anywhere.

Personality: a trusted senior consultant, not a toy. It touches real financial data — the design must feel precise, calm, and trustworthy. B2B professional, not consumer-playful.

## Platform & technical context (constrains the design)

- React Native + Expo, one design system for iOS and Android; respect platform conventions where they diverge (back gestures, sheets, notification behaviors).
- Agent turns are LONG: 30 seconds to 12 minutes. The app cannot stream in the background — the pattern is: watch live while foregrounded; leave freely; a push notification brings you back; the thread refetches and catches up. Design must make "you can leave" explicit and returning seamless.
- Two push notification classes: (1) "Task finished" (agent completed/errored), (2) "Needs your decision" (agent wants approval for an ERP write). Class 2 is high-priority/time-sensitive. Notification actions ("Approve…", "View") do NOT commit anything from the notification itself — platform constraints make that unreliable — instead they deep-link into a **focused in-app approval sheet**: app opens directly onto the approval with a Face ID/biometric prompt, then one tap commits. Design this fast-path sheet as a first-class moment (target: lock screen → decided in under 5 seconds). Note: on iOS, action buttons only appear when the user long-presses/expands the notification; a plain tap deep-links to the same sheet.
- All state lives server-side; the app is a viewer/controller. Offline = read cached conversations + a clear reconnect banner; composing while offline queues nothing (disable send, explain why).
- Login is unusual and must be designed well: the user is already logged into Jarvis on their DESKTOP web app. The mobile app pairs to their account by scanning a QR code shown in the web app's settings (fallback: type the workspace URL manually), then completes sign-in in the system browser (OAuth). No in-app password entry, ever. Pairing includes a verification step: the phone displays a 2-digit code that the user confirms on the desktop web page ("Does your phone show 47?") before sign-in proceeds — design this as a trust-building moment, not friction.

## v1 feature list (design ALL of these)

> Scope note: v1 is FULL feature parity with the web chat app — chat, approvals, skills, macros, agents, files, settings, account. Everything reachable from a sidebar menu.

1. **Welcome & pairing**: value-prop intro (1-2 screens max) → "Scan the QR code from your Jarvis web app" camera screen → 2-digit match code display ("Confirm this code on your computer: 47") → system-browser sign-in handoff → success state with device name confirmation. Include manual "enter workspace URL" fallback and clear error states (expired QR, code mismatch/cancelled on desktop, wrong account, site unreachable).
2. **Navigation shell — sidebar menu (drawer)**: hamburger-opened drawer as the primary feature switcher, mirroring the web sidebar: user avatar + name + workspace (company) at top, then Chats, Approvals (with badge), Skills, Macros, Agents, Files, and at the bottom Settings + Account. Keep the two highest-frequency destinations (Chats, Approvals) additionally reachable as bottom tabs or persistent shortcuts — design the interplay so the drawer is discovery/switching and the tabs are daily use. Show sync/connection status subtly in the drawer.
3. **Conversation list (home)**: conversations with title, snippet, timestamp; states clearly distinguishable at a glance — agent currently working (live indicator), needs your decision (prominent), errored, idle. Search, star, archive. Pull-to-refresh. New-chat FAB or equivalent.
4. **Chat thread**:
   - User + assistant messages; assistant messages stream in live token-by-token when foregrounded.
   - Tool activity timeline: while working, the agent shows human-readable steps ("Reading Sales Invoice INV-00042", "Checking stock levels…") as a collapsible narrated activity log — NOT a progress bar. Set duration expectations ("this may take a few minutes — you'll be notified") with an explicit leave-and-be-notified affordance.
   - Rich results: tables, charts, and document previews rendered in-thread (design a card system for ERP data: invoice summary card, list-of-records card, chart card).
   - Error + retry states on messages; "catching up…" state after returning from background.
   - Attachments: photo/camera/file into the composer.
   - Composer: text field, attach button, mic button (dictation — see v1.1, design the button now), send. Stop button while a turn runs (cooperative stop — design a brief "stopping…" state, since the agent finishes its current step before halting).
5. **Approvals inbox** (a top-level tab — this is the killer feature): work-queue grouped "Needs attention / Done" in v1 — but lay it out so a third "Scheduled" group (recurring/proactive agent tasks) can slot in later without redesign. Each approval opens a detail view showing EXACTLY what the agent wants to do: document type + name, every field change (old → new), amounts highlighted, save-vs-submit badge, the agent's stated reason, link to the source conversation. Approve (biometric-gated) / Deny with optional note. Handle "decided elsewhere" (approved on web while you looked) gracefully — the same "Already handled" state also appears when arriving from a stale notification. Badge counts on the tab.
6. **Skills**: the user's library of custom skills (reusable instructions/playbooks the agent follows). List with search; skill detail showing its content (markdown) with edit; create-new flow (name, description, instructions); "apply to agent" action with a brief progress state (the agent restarts to pick up skills — communicate this honestly: "Updating your agent… ~1 min"). Include a "Learned" section: suggestions the agent has learned from conversations, presented as review cards (accept into a skill / dismiss).
7. **Macros**: saved multi-step routines the user can run on demand. List with run button; a run screen showing live step-by-step progress (macros emit progress events) with success/failure per step; macro detail with editable steps — on web this is drag-and-drop, on mobile design touch-friendly reordering (drag handles, long-press). Create-new macro flow.
8. **Agents**: gallery of available agent presets/specialist personas; agent detail (what it does, its skills/tools) with a "Start chat" action that opens a new conversation with that agent.
9. **Files (File Box)**: the workspace file library — browse/search files, upload (camera/photos/documents), preview (images, PDFs), and "send to chat" to attach a file into a conversation. Show which conversation a file came from where known.
10. **Notifications**: notification settings screen (per-class toggles: task-finished, needs-decision; per-conversation mute); in-app banner when something completes while you're in another screen; notification-health self-check ("Notifications working ✓ / No device registered — fix"). Deep links land on the exact conversation/approval. Include a notification-permission priming screen (especially Android 13+, where the OS permission prompt needs context first) and a "new device signed in" security alert pattern (shown on all devices when a new phone pairs).
11. **Settings (user settings)**: chat preferences (default model picker, thinking level, the auto-apply-changes toggle — mark this one visually as consequential, it disables write confirmations), appearance (light/dark/system), notification prefs (links to #10), this device + other paired devices (rename, sign out remotely), help/about/version.
12. **Account details**: workspace/company info, current plan and subscription status, renewal date, usage meter (tokens/requests this month). Read-only in-app: plan changes and billing happen on the web — provide a "Manage billing on the web" link-out rather than any in-app purchase flow (app-store IAP policy). Design the usage meter to be glanceable.
13. **System states**: skeleton loading, empty states (no conversations yet, no approvals, no skills/macros/files — make these warm and instructive, each with a "how to create your first" hint), workspace-unreachable, session-expired (re-pair flow), update-required (blocking force-upgrade screen — the server can require a minimum app version).
14. **Lock-screen live progress (differentiator — design it)**: iOS Live Activity / Android live notification showing batch task progress ("Posting invoices… 12/45") with the Jarvis identity. No major AI assistant ships this today.

## v1.1 previews (design direction now, build later)

- Voice: push-to-talk dictation with live waveform, editable transcript before send, autosend toggle (think warehouse/shop-floor use).
- Home-screen widget: pending-approvals count + quick-ask.
- Passkey upgrade for sign-in.
- One-tap approve directly from the notification (no app open) — reserve visual language for it.

## UX patterns to follow (from a field study of ChatGPT/Claude/Gemini/Perplexity/Copilot mobile)

- Long tasks: narrated activity feed + upfront duration expectation, never a fake progress bar. The turn belongs to the thread, not the screen — navigating away is always safe and stated.
- Approvals: show the exact change, never a bare "Proceed? OK". Approve is deliberate (biometric), Deny is easy, both are auditable.
- Batch jobs: plan-then-approve — the agent presents one editable plan, gets ONE approval, then runs (not 40 sequential confirmation interrupts).
- Push hygiene: suppress pushes for the conversation currently on screen; email is the fallback channel for unseen results.
- Multi-device: everything syncs; a decision made on web reflects on mobile within seconds.

## Design system requirements

- **Consistency with the existing web app is a hard requirement.** The web UI is built on the frappe-ui design language: minimal and calm, neutral gray surfaces with semantic "ink" (text) and "surface" (background) color scales, the Inter typeface, Feather icons, restrained radii, and consistent status-color semantics. The mobile app must read as the same product: same palette and semantic tokens, same type family and scale relationships, same iconography (Feather), same component shapes and variant logic (solid/subtle/ghost buttons, quiet badges). Where you introduce mobile-only components (drawer, sheets, approval card), derive them from this language rather than inventing a new one. The exception: navigation and gestures follow native platform conventions — consistency means the design language, not embedding the website.
- Light + dark from day one; dark must be first-class (ops people check phones at night).
- Information-dense ERP data made glanceable: strong typographic hierarchy, tabular numerals for amounts, currency formatting, status color semantics (draft/submitted/cancelled) used consistently.
- Accessibility: 44pt+ tap targets, dynamic type support, WCAG AA contrast, one-handed reachability for primary actions.
- Motion: streaming text, live-status pulses, and approval-success moments deserve subtle, fast motion; nothing bouncy.
- Deliverables wanted: screen map + user flows (pairing incl. number-match, long-task-with-push roundtrip, approval roundtrip from lock screen, macro run with live progress, skill create-and-apply), high-fidelity mockups of every v1 screen in light+dark, a component sheet (drawer/sidebar menu, message bubbles, tool-step timeline, ERP data cards, approval diff card, list rows for skills/macros/agents/files, status badges, banners, usage meter), and interaction notes for streaming/reconnect/catch-up states.
