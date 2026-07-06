# Jarvis Mobile App — Client Tech Stack & UI Consistency Strategy

> Companion to `2026-07-06-mobile-backend-design.md` (backend contract) and `ui-ux-design-prompt.md` (design brief). Added 2026-07-06 after the user's requirement: **the mobile UI must be consistent and uniform with the web UI.**

## What the web UI is made of (verified in `apps/jarvis/frontend/`)

| Ingredient | Web implementation | Evidence |
|---|---|---|
| Design tokens | Tailwind 3 with the **frappe-ui preset**; semantic color families `text-ink-*` / `bg-surface-*` | `frontend/tailwind.config.js` (`presets: [frappeUIPreset]`; safelist limited to ink/surface) |
| Typography | **Inter** (InterVar, bundled locally by frappe-ui — no Google Fonts link) | `jarvis/www/jarvis.html` comment |
| Icons | **Feather** icon set via frappe-ui's `FeatherIcon` | 48 `FeatherIcon` usages across `frontend/src/` |
| Components | frappe-ui 0.1.278 (Button, Dialog, ListView, FormControl…) | `frontend/package.json` |
| Charts/canvas | Agent-generated canvas items rendered as sandboxed HTML/SVG (`<iframe srcdoc>` from `get_canvas`); echarts + mermaid inside | `ChatView.vue`, `jarvis/chat/api.py:204` |
| Theme | Light + dark, token-driven | pre-boot dark flash guard in `jarvis.html` |

## Chosen mobile stack

**React Native + Expo, TypeScript (strict).** Rationale (full evidence in `research-stack-evaluation.md`): Raven — the Frappe ecosystem chat app with Jarvis's exact requirements — launched on Capacitor and rewrote on RN + Expo in 2025 (webview socket suspension, missing notification actions, store-review risk); Frappe's own Flutter app is abandoned; RN keeps the team's TypeScript and enables shared packages with the web app.

### UI layer — how "consistent and uniform with web" is achieved

1. **NativeWind v4** (Tailwind CSS for React Native): same utility-class styling model as the web app.
2. **Shared design tokens — the single-source-of-truth move.** Extract the token layer the web already uses (frappe-ui's `ink`/`surface` semantic color scales, spacing, radii, font-size scale) into a monorepo package `@jarvis/design-tokens`, consumed by BOTH:
   - the web app's `tailwind.config.js` (alongside the frappe-ui preset it already uses), and
   - the mobile app's NativeWind `tailwind.config.js`.
   One token change updates both UIs; the two front ends cannot drift in color, spacing, or type.
3. **`@jarvis/ui-native` — a thin in-house component kit** (~15–20 components) styled with NativeWind against those tokens, mirroring frappe-ui's component anatomy and variant names: Button (solid/subtle/ghost/outline), Badge, Sheet (mobile analog of Dialog), ListRow, FormControl, Banner, Toast, Card, Avatar, EmptyState, SkeletonRow, StatusDot. Optionally seeded from **react-native-reusables** (shadcn-style unstyled RN primitives on NativeWind) so accessibility/interaction primitives aren't built from scratch — we restyle, not reinvent.
   - Why not an off-the-shelf library: React Native Paper = Material Design (wrong aesthetic), Tamagui/gluestack = their own design systems (constant fighting to look like frappe-ui). A thin kit over shared tokens is less code than overriding a foreign design system.
4. **Icons: Feather via `@expo/vector-icons`** — the literal same icon set as the web's `FeatherIcon`. Zero visual drift, first-party with Expo.
5. **Font: Inter** via `expo-font` (`@expo-google-fonts/inter`) — same face as web's InterVar; tabular numerals for amounts, matching the design brief.
6. **Dark mode:** same light/dark token pairs through NativeWind `dark:` variants; theme setting (light/dark/system) in the Settings screen.
7. **Canvas/charts consistency for free:** agent canvas outputs (charts, tables, documents) are rendered in a sandboxed **react-native-webview** fed by the same `get_canvas` HTML/SVG the web puts in its iframe — pixel-identical rich output with zero re-implementation (dark flag passed through, as the web does).
8. **The deliberate exception:** navigation, gestures, and system surfaces stay native (drawer, sheets, back-swipe, platform transitions, biometric prompts). Consistency means the Jarvis design language — tokens, type, icons, component shapes, status-color semantics — not embedding the website. That distinction is what keeps chat fast and the app clear of App Store Guideline 4.2 webview scrutiny.

### Full stack table

| Concern | Choice | Why / maps to |
|---|---|---|
| Framework | **Expo (React Native), TypeScript strict** | Raven precedent; team TS skills; EAS tooling |
| Styling | **NativeWind v4** + `@jarvis/design-tokens` | Token-level uniformity with the web UI (above) |
| Components | **`@jarvis/ui-native`** (in-house, optionally seeded from react-native-reusables) | frappe-ui look; no foreign design system to fight |
| Icons / font | **@expo/vector-icons (Feather)** / **Inter (expo-font)** | Same set/face as web |
| Navigation | **Expo Router** (drawer + tabs + stacks on React Navigation) | File-based routes; first-class `jarvis://` deep links for push taps |
| Server state | **TanStack Query** | Invalidate-on-focus/reconnect = the backend's catch-up-refetch contract (`home_snapshot` + `sync_conversation`) |
| Client state | **Zustand** (small stores: streaming buffer, composer, session) | Mirrors the web's hand-rolled minimal store philosophy |
| Realtime | **socket.io-client v4** (`transports:['websocket']`, `extraHeaders` bearer + Origin) | Backend design §4 |
| Auth | **expo-auth-session** (PKCE) + **expo-secure-store** (`AFTER_FIRST_UNLOCK`) + **expo-local-authentication** (biometric approval sheet) | Backend design §1, amendment B |
| Push | **expo-notifications** (native FCM/APNs tokens) + **Notifee** (Android data-message rendering, channels `jarvis_tasks`/`jarvis_decisions`) | Backend design §2 platform mapping |
| Lists | **FlashList** | Long chat threads / conversation lists at 60fps |
| Message rendering | **react-native-markdown-display** (+ dompurify-equivalent sanitization server-side already) | Messages are markdown |
| Canvas/rich output | **react-native-webview** (sandboxed, fed by `get_canvas`) | Identical rich output to web |
| Media/QR | **expo-camera** (QR scan), **expo-image**, **expo-document-picker** | Pairing + attachments + File Box |
| OTA + CI | **EAS Build / Submit / Update** | Store pipeline + JS-level hotfixes (policy-compliant) |
| Monorepo | **pnpm workspaces**: `apps/mobile`, `packages/design-tokens`, `packages/api-client`, `packages/schemas` | Shared TS between web and mobile (Raven pattern, ~40% reuse) |
| Testing | Jest/Vitest for shared packages; **Maestro** for on-device e2e flows (pairing, chat turn, approval) | e2e the flows the backend design names |

### Where the shared packages come from

- `packages/schemas` — request/response types for every endpoint in backend design §3 (the additive-only versioning contract is enforced here: unknown fields tolerated, nothing removed).
- `packages/api-client` — typed wrapper over `/api/method/*` with bearer auth, refresh-on-401 (foreground only), and the `{ok, data|error}` envelope; consumed by mobile now, adoptable by the web SPA later.
- `packages/design-tokens` — the extraction described above; the only package the web app adopts on day one (a no-visual-change refactor of its tailwind config).

## Explicit non-choices (and why)

- **Flutter** — no team/skill/code overlap, Frappe ecosystem abandoned it (see `research-stack-evaluation.md`).
- **Capacitor wrap of the Vue SPA** — desktop-first SPA (1 media query, 4k-line ChatView), iOS webview socket suspension, no notification actions, Guideline 4.2 risk; kept only as a documented emergency stopgap.
- **React Native Paper / Tamagui / gluestack as the component base** — each imposes a non-frappe design language; overriding them costs more than the thin token-native kit.
- **Expo's hosted push service** — native FCM/APNs tokens go straight to our relay (zero extra third party; backend design §2).
- **Re-implementing charts natively** — WebView rendering of `get_canvas` output keeps parity; revisit only if performance data demands it.
