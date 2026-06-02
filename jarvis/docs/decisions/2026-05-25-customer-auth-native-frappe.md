# Customer→Admin auth: native Frappe api_key:api_secret

**Date:** 2026-05-25
**Status:** Accepted

## Decision

We use Frappe's native `Authorization: token <api_key>:<api_secret>` to
authenticate customer benches against the admin's customer-facing endpoints.
Per-customer data isolation is enforced via Frappe's User Permission system,
scoped to the customer's `Jarvis Customer` row (which Frappe extends to
Subscription + Tenant via the `customer` Link field).

## Alternatives considered

- **Custom Bearer token + `@customer_auth_required` decorator (previous design).**
  Worked but required `allow_guest=True` on every endpoint (caught us twice
  in one day after Frappe 17's OAuth-strict change). Isolation lived in
  endpoint code - a new endpoint forgetting `customer.name` filter would leak.
- **Helper-only fix (`customer_owned(doctype, name)`).** Smaller PR but still
  relies on developers using the helper - a missed call still leaks.

## Why this won

- Frappe enforces auth at `validate_auth()` time, before any of our code.
- `frappe.has_permission(...)` from a customer session reports False for
  cross-customer rows - that's the signal protecting the HTTP API surface.
- We already create the Frappe User per customer (`v1_4` patch); native
  auth just uses what's already there.

## Trade-offs accepted

- Customers send two values (`api_key` + `api_secret`) instead of one Bearer
  token. Slight ergonomic cost; documented in configuration.md.
- Site-binding (`X-Jarvis-Site` header) is dropped. User Permission gives
  stronger per-customer isolation than a soft header check.
- Existing customers re-onboard at cutover (greenfield) - acceptable today
  with one local-dev customer; would require coordination at scale.
- Frappe's User Permission propagation enforces at the **request boundary**
  (REST API, form loads). Internal Python `frappe.get_doc(...)` and
  `frappe.get_all(...)` are trusted code paths that bypass the check. Our
  endpoints don't accept customer-supplied IDs, so this gap doesn't open
  a leak; future endpoints should follow the same pattern.

## When to revisit

- If we add customer-facing OAuth/OIDC for SSO.
- If a leaked api_key:api_secret causes a real incident and we need
  short-lived tokens.
- If a future endpoint pattern accepts user-supplied resource IDs - that
  surface needs explicit ownership checks, since framework-level User
  Permission doesn't catch internal Python calls.
