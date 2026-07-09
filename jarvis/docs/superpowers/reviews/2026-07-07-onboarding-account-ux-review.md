# Onboarding & Account — UX/UI review

> Human-reviewer pass over the Jarvis customer SPA (`frontend/src`). Reviewed the
> live `LlmPoolEditor` + `AccountView` in the browser (site.jarvis:8002) and the
> full source/CSS of `OnboardingView.vue`, `LlmPoolEditor.vue`, `AccountView.vue`,
> `AppShell.vue`. Date: 2026-07-07. Branch: `enhancing-onboarding-process`.

Legend: **[V]** visually confirmed in browser · **[C]** from code/CSS review.

---

## Part A — Onboarding wizard (`OnboardingView.vue`)

### A1. Connect-AI step shows the full 3-tab proxy editor (primary change)
**[V/C]** The final "Connect your AI" step embeds the shared `LlmPoolEditor`,
which exposes **Quick | Preset | Custom** tabs plus a **Direct / Proxy (failover)**
badge. For a first-run user this is a lot of surface:
- *Preset* = a technical catalog ("Single-vendor resilience", "Cross-vendor
  strategies": Balanced / Cost-saver / Max-reliability) — pooling/failover concepts.
- *Custom* = an add/remove/reorder failover pool with per-row credential toggles,
  base-URL, rotation strategy, etc.
- The *Direct / Proxy* badge is jargon at signup time.

**Action (this PR):** remove Preset + Custom from onboarding; leave a single
Quick model. Advanced pooling stays available on the Account page. Fastens
signup and removes decision-paralysis — matches the requested change.

### A2. Quick hint text pushes users toward the complex tabs
**[V/C]** Quick tab copy: *"A single model, sent directly to the provider. Need
multiple models with failover? Use **Preset** or **Custom**."* During onboarding
this actively steers new users into the surface we're trying to hide. Must drop
the Preset/Custom reference when those tabs aren't present.

### A3. Editor's "Save configuration" button breaks the wizard's button language
**[V]** Inside the wizard card, the embedded editor's primary button is a solid
dark **"Save configuration"** button, while every other wizard button uses the
lighter `.jv-ob-btn-primary` (blue-tinted outline) style. Two different primary
styles on the same screen. Also the label "Save configuration" reads like a
settings screen, not a signup step ("Connect", "Finish", "Continue" would fit).

### A4. Wizard renders with the full app sidebar (not chrome-less)
**[C]** `AppShell` renders the global `Sidebar` around **every** route, including
`/onboarding`. So the "Set up your workspace" wizard shows the whole app nav rail
(Chat / Skills / Macros / …) beside it. A first-run signup flow reads better as a
focused, chrome-less page. (Defensible since onboarding is now "invited" from
inside the app, but worth revisiting.) — *noted, not in this PR's scope.*

### A5. Self-host card uses error-red for an informational note
**[C]** The "Not included: persona, skills, managed proxy…" line on the
Self-hosted mode card is styled with `var(--red)` (the danger color). It's
informational, not an error; amber/muted would be less alarming.

### A6. Mode cards use emoji icons (☁ / 🖥)
**[C]** The header uses a crisp SVG brand mark, but the two mode cards use OS
emoji, which render inconsistently across platforms and clash with the brand
mark. Minor/cosmetic.

### A7. Step indicator omits the mode-choice + self-host steps
**[C]** The 4-dot stepper (Account/Plan/Pay/Connect AI) is hidden on the
mode-choice screen and entirely absent for the self-host track (single step), so
those paths have no "where am I" cue. Minor.

---

## Part B — The change shipped in this PR

Add an opt-in `modes` prop to `LlmPoolEditor` (default = all three tabs, so
`AccountView` is unchanged). Onboarding passes `:modes="['quick']"`. When only
one mode is allowed:
- hide the mode-tab bar and the Direct/Proxy badge (both meaningless with one mode);
- force `llmMode` to the single allowed mode (never auto-switch to preset/custom);
- drop the "Use Preset or Custom" sentence from the Quick hint and point users to
  Account for advanced setup instead.

Only two consumers exist (`OnboardingView`, `AccountView`), so the prop is safe.
The Quick credential toggle (API key ↔ Chat subscription) stays — a single model
of either kind is still "quick/direct", not proxy config.

**B2 — Simplify the onboarding chat-subscription path.** In the quick-only editor
(`singleMode`), the chat-subscription row now hides the **Model ID** field and the
**rotation** dropdown (Sticky / Round-robin / Least-used) — the provider is
enough at signup. The model auto-defaults per provider via a new pure
`defaultSubscriptionModel(upstream)` helper (openai→`gpt-5.5`, google→
`gemini-2.5-pro`), so `validatePool`/save still get a model id. The full Account
editor is unchanged (keeps model + rotation for real pools).

**B3 — Restore "Reconnect" (re-authorize) on the Account page.** The old desk
page had a *Re-authorize* button on a connected subscription ("If chat starts
failing, click Re-authorize to mint fresh tokens"); the SPA dropped it. Added a
per-account **Reconnect** button (shown when the full editor is used, i.e. not in
the simplified onboarding view) that re-runs the paste-back OAuth flow. Connected
accounts now dedupe by `account_ref` on finish, so re-authorizing the same
account refreshes it in place instead of adding a duplicate row.

### Verification
- `node --test` — 28/28 pass, incl. a new `defaultSubscriptionModel` case.
- `vite build` — exit 0; `OnboardingView`, `AccountView`, `LlmPoolEditor` all
  compile cleanly.
- Live human-reviewer pass over the *current* `AccountView` + `LlmPoolEditor`
  (Quick/Preset/Custom) in the browser.
- Live render of the *new* onboarding wizard was blocked by the SPA's server-side
  boot injection (dev server can't mint `is_system_manager`/CSRF for the deep
  worktree; a real render needs a Frappe-served build). Flagged as a follow-up.

---

## Part C — Account page (`AccountView.vue`) — review for /goal

### C1. Double sidebar (highest-impact) [V/C]
`AppShell` already wraps the route in the global `Sidebar`; `AccountView` (and
`MonitorView`) *additionally* render their own `<AppSidebar>` (Jarvis · Chat /
Account / Usage). Result: **two stacked nav rails** on the account page. Redundant
and inconsistent with the rest of the app (ChatView uses only the shell sidebar).

### C2. Raw backend exception leaked to the user [V]
Plan & billing rendered: *"admin authentication failed; check the bench's admin
credentials. **(frappe.exceptions.AuthenticationError)**"* — the internal
exception class is shown verbatim. Error copy should be human ("We couldn't reach
billing right now — try again shortly.") and never expose exception types.

### C3. Inconsistent primary-button / card language across pages [V/C]
Onboarding (`.jv-ob-*`), the editor (inline styles), and Account (`.jv-acct-*`)
each define their own button + card treatments over the same theme tokens. The
"Save configuration" (solid dark) vs "Upgrade →" (small blue outline) vs wizard
primary (blue-tinted) buttons don't share one primary style. Worth a shared
button/card primitive.

### C4. Heading scale differs across surfaces [C]
Onboarding H1 = 28px, Account H1 = 20px, card H2 = 14px. Expected wizard-vs-
settings contrast, but flag for a cohesive type scale.

> C1–C2 are concrete bugs; C3–C4 are consistency debt. To be confirmed/expanded
> in the Account-focused pass after the onboarding change lands.
