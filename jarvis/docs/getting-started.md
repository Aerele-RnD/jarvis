# Getting started (Jarvis Cloud)

The production path: connect your Frappe site to **Jarvis Cloud**, where Aerele's
control plane assigns and manages your openclaw agent container. You don't run
Docker or openclaw — you sign up, pay, and start chatting. (For a self-managed
single-bench setup, see [local-dev.md](local-dev.md) instead.)

## 1. Install the app
```bash
bench get-app https://github.com/Aerele-RnD/jarvis --branch main
bench --site <your-site> install-app jarvis
```

## 2. Onboard
Open **`/app/jarvis-onboarding`** in Desk. Enter your email + company, pick a
plan, and **Sign up & pay** (Razorpay Checkout). On success the control plane:
- creates your customer account + a portal user,
- assigns a warm openclaw container from the fleet,
- returns its connection (`agent_url` = `wss://<you>.jarvis.aerele.in`, plus an
  agent token) and your admin api token.

These are stored in **Jarvis Settings** automatically — you don't edit them.
(The page also has a **Sync connection** button to re-fetch, and **Renew / Pay**
to extend when your period lapses — see Billing below.)

## 3. Set your LLM credentials
In **Jarvis Settings → Language Model**, choose your provider + model and paste
your LLM API key. Save. The app sends these to the control plane over HTTPS,
which applies them to your container. (See [configuration.md](configuration.md).)

## 4. Chat
Open **`/app/jarvis-chat`** and ask a question — e.g. "list my 5 newest
customers". The agent answers using **your** Frappe data, scoped to the asking
user's permissions (see [architecture.md](architecture.md) for how identity
flows). It can read schemas/docs/lists/reports and, with confirmation, create or
update records — the full toolset is in [tools-api.md](tools-api.md).

## Billing
Plans are **pay-as-you-go** — both monthly and annual are one-shot payments;
**nothing auto-charges**. When a period lapses your container is stopped after a
short grace period (your data is preserved); click **Renew / Pay** on the
onboarding page to extend and restart it.

## Running the platform yourself?
Operators bringing up the Jarvis Cloud control plane + fleet should follow the
`jarvis_admin` app docs — start at its **`docs/production-deploy.md`** (the full
go-live sequence). This `jarvis` app is only the customer side.
