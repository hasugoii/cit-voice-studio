# SaaS foundation — manual plans

Owner: `/saas/admin` (existing owner Basic Auth). Customers: `/saas/`.
Customer API: `/saas/api`, using their own `sv_` API keys. The original owner
`/public-api` key stays separate and is not suitable for distributing to customers.

All Trial/Pro/Business templates start disabled and draft as requested. Quotas are
editable template examples, not throughput recommendations or published prices.
Trial price defaults 0, paid plan prices are unset. There is no Stripe integration,
automatic charging, receipt, invoice or automatic verification of bank transfers.
Owner reviews payment outside this app, edits price/limits, enables a non-draft
plan, then creates/assigns customer accounts. Public signup is off by default;
it can be opened only once Trial is enabled. Opening signup gives Trial to new
accounts, not paid plans. A plan can have a manually assigned expiry per account.

Quotas: Unicode NFC code points, stripped leading/trailing whitespace; monthly
calendar in Asia/Tokyo. Quota is reserved atomically before inference, committed
only on success and refunded on errors/restart. Returned audio counts as rendered
usage; a client disconnect after completed inference is not a refund. Changing
plans does not reset monthly usage. Only one SaaS inference runs at a time;
additional requests return 429 (not an unbounded background queue).

DB: `/data/CitVoiceStudio/saas.sqlite3` (WAL). Persists via existing data volume.
Passwords salted+scrypt, sessions opaque hashed tokens (Secure/HttpOnly/SameSite
Strict cookies), API keys only hash+prefix persisted and shown once. Session
mutations require CSRF token; all supplied Origins must match public origin.
Login throttled by account and connection peer. Under a shared proxy, peer limits
may affect several users together; this is an initial abuse guard, not distributed
rate limiting. Owner admin requires nginx Basic Auth plus backend loopback guard;
external forwarded requests cannot enter admin routes. Do not publish backend
port or alter admin forwarding rules without revalidating access boundaries.

Customers cannot change model, clone voices, access owner history, or access other
users' keys/usage. Only preset voices are listed and allowed for customer inference.
All customers share the currently active engine; Kokoro doesn't read Vietnamese.
Suspension/expiry checked on every authenticated request. Revoked keys stop working
immediately. No password reset/email verification yet; owner-assisted onboarding.

Before scale-up: owner must choose commercial terms/pricing, evaluate model voice
licenses for intended use, and measure actual long-form/concurrent workload. This
release is a functioning manual-service foundation, not automated paid billing.
