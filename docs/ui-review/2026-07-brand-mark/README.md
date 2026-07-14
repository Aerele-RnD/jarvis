# Brand mark — one star, one gradient (PR #300)

Before/after captured from the running app (`jarvis.proxy`, light theme, 1440px) so the PR
can point at the exact defect each commit fixes, rather than asking a reviewer to take the
diff on trust. Same convention as `2026-07-ai-models-onboarding/`.

Colours below are `getComputedStyle` readings taken in the browser at the moment of capture,
not eyeballed from the image.

| # | Before | After | The defect |
|---|---|---|---|
| 01 | `before-01-two-logos-one-screen.png` | `after-01-two-logos-one-screen.png` | **Two different logos on one screen.** The 54px welcome-hero mark painted `linear-gradient(135deg, rgb(28,28,34), rgb(139,92,246))` — near-black→purple — while the 28px sidebar mark two inches away painted `rgb(110,139,255) → rgb(139,92,246)` — blue→purple. The hero had hand-pasted `JarvisMark`'s gradient but used `var(--blue)` as its first stop, and PR #294 repointed `--blue` from indigo to near-black. **Distinct colours on screen: 2 → 1.** |
| 02 | `before-02-assistant-avatar-near-black.png` | `after-02-assistant-avatar-brand-gradient.png` | **The assistant avatar — beside every single Jarvis reply — was a flat near-black chip**, `rgb(28,28,34)`, because it was painted `background: var(--cta)`. Since `--cta` inverts by theme it also went *near-white* in dark, which would have put a white star on a white chip; that is the only reason a `.jv-dark .jv-logo { … !important }` rule existed, to force the gradient back in dark. Both the chip and the hack are gone. |

## Also visible in 02

The invoice card titles (`ACC-SINV-2026-00003`, …) are **near-black in the before shot and a
blue link in the after**. That is `.jv-card-link`, which was still on `--cta` — the same
near-black-looks-like-body-text bug this PR fixes in `ReceiptChip`. It was caught in review of
this PR and fixed in `91cf8bd`; the screenshots picked it up incidentally.

## Not captured

- **Dark mode.** The `--cta` chips are *near-white* in dark, so the before-state there is a
  white star on a white chip — but the `!important` rule masked it, which is exactly why the
  bug survived so long. The after state is verified by computed style (all marks resolve to
  one gradient in both themes), not by image.
- **The onboarding tour bubble** (white-on-near-white, 1.18:1 → 14.39:1). Both local sites are
  onboarded, so the route guard redirects away from the tour and the screen cannot be reached
  without un-onboarding a tenant. Verified compositionally instead: the compiled rule is
  `background: var(--cta); color: var(--cta-fg)`, and the dark tokens resolve to
  `#ececf0` / `#1c1c22`.
- **PWA and Frappe Desk icons.** Changed in this PR (both were entirely different marks on
  different gradients) but not screenshotted — they need a phone viewport and a Desk session
  respectively.
