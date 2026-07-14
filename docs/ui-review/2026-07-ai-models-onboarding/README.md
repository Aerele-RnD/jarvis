# AI models + onboarding UI pass — 2026-07

"Before" screenshots captured from the running app while the issues were being
reported. They are kept here so the PR can point at the exact defect each commit
fixes, and so a future reader can see *why* a rule exists rather than guessing.

| # | Before | The defect |
|---|---|---|
| 01 | `before-01-onboarding-disabled-button-white-on-hover.png` | `.jv-ob-btn:hover` (specificity 0,2,0) outranked `.jv-ob-btn--primary` (0,1,0), so hovering a **disabled** primary button repainted it `--surface-3` while `color` stayed `--surface` → white-on-white. The button vanished under the cursor. |
| 02 | `before-02-onboarding-blue-focus-ring.png` | `@tailwindcss/forms` paints a blue focus ring on every bare input. The suppression was scoped to `.jv-root` (chat); onboarding is a **separate root** (`.jv-ob-root`), so it never got it. The plugin rings via `box-shadow`, not `outline`, so JvCombo's `outline: none` never killed it. |
| 03 | `before-03-settings-dialog-dead-space.png` | Dialog was a hard `560px`; the compact AI-models pane left roughly half of it empty, with Save floating mid-panel. |
| 04 | `before-04-ai-models-duplicate-heading.png` | The dialog already titles the pane ("AI models"), so an uppercase "AI MODELS" repeated directly beneath it was pure duplication. |
| 05 | `before-05-config-panel-messy-account-rotation.png` | Four fields crammed across one flex row with ratios 1 / 1.5 / 1.5 / 1.5 → four different widths. Plus an "Account rotation" control that only means anything once one provider has several accounts. |
| 06 | `before-06-connect-account-placement.png` | "Connect account" hung under the form on the left, next to a redundant "No accounts connected yet." line. |
| 07 | `before-07-native-os-dropdown.png` | A native `<select>` — drawn by the **OS**, with its own popup. This is why settings looked nothing like onboarding, which uses the app's `JvCombo`. |
| 08 | `before-08-connect-flow-redirects-first.png` | Clicking "Connect account" threw you straight at ChatGPT, and only *then* showed a panel telling you to "Open sign-in" — an action you had already, involuntarily, taken. |

## Why no "after" screenshots here
The after state is on `main` once this merges, and is live on the running bench.
They were not captured to disk because the browser tooling used in this session
returns screenshots in-context only. Reviewers should pull the branch (or look at
the deployed site) rather than trust a static image.
