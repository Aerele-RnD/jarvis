# Jarvis Mobile App — v1 design package

**Status: design complete (2026-07-06), not implemented.** These documents are the source of truth for the mobile-app feature request; the tracking issue links here.

## Reading order

1. **[2026-07-06-mobile-backend-design.md](2026-07-06-mobile-backend-design.md)** — the backend design: auth/QR pairing, push pipeline (`jarvis-push-relay`), mobile API contract, realtime/catch-up, new doctypes, security model, failure modes, ops/rollout, non-goals. Adversarially verified (9-agent design workflow); the changelog at the end records what that pass changed.
2. **[client-tech-stack.md](client-tech-stack.md)** — chosen mobile stack (React Native + Expo, TypeScript) and the UI-consistency strategy: NativeWind v4 + shared `@jarvis/design-tokens` extracted from the web's frappe-ui preset, thin `@jarvis/ui-native` kit, Feather icons, Inter.
3. **[ui-ux-design-prompt.md](ui-ux-design-prompt.md)** — self-contained design brief (paste into a Claude design session) with the full v1 feature list: chat, approvals, skills, macros, agents, files, settings, account — full web-UI parity behind a sidebar drawer.

Supporting evidence (research reports behind the decisions):

- [research-ai-app-field-study.md](research-ai-app-field-study.md) — UX patterns from ChatGPT/Claude/Gemini/Perplexity/Copilot mobile
- [research-stack-evaluation.md](research-stack-evaluation.md) — RN+Expo vs Flutter vs Capacitor (Raven precedent)
- [research-spa-exploration.md](research-spa-exploration.md) — what the existing Vue SPA reuses/exposes for a native client

## Hard GA gate (do not ship without)

Mobile bearer tokens widen existing IDOR exposure, so GA is gated on the security-audit fixes for **JRV-SEC-002** (conversation owner checks) and **JRV-SEC-B** (unguarded endpoints), plus server-side gating for `apply_custom_skills` / `set_auto_apply`. Details in backend design §6.
