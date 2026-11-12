# Admin account/session migration — 2026-11-13

Baseline: nginx Basic Auth protects owner, SaaS admin backend trusts local
forwarding. No admin login/session/logout UI; customers already use separate
session and API-key tables. Owner requested proper admin account login.

Change: dedicated admin_users/admin_sessions (no dependence on a customer plan),
scrypt password, hashed opaque 12-hour HttpOnly/Secure/SameSiteStrict cookie,
CSRF for admin mutations, login throttle, logout and password change. Nginx
auth_request checks session for owner engine routes; no Basic Auth bypass/fallback.
First account provisioned by trusted CLI only, no public setup endpoint. Keep
current owner password as initial password, username admin, no plaintext in Git.

Thresholds before deploy: anonymous owner redirects to login; admin API 401 without
WWW-Authenticate; correct admin session accepted remotely; customer/API keys/local
headers cannot elevate; CSRF/Origin validated, logout/expiry/password change revoke
access. Existing plans/customer data preserved through additive migration and
online SQLite backup before provisioning. Full existing tests plus new auth tests
and real nginx auth_request/browser login required before declaring complete.
