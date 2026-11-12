# Admin account/session migration — 2026-11-13

Status: closed after source, real nginx and live browser validation.

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

Results: 105 backend tests, 17 React tests and admin/customer UI contract tests
pass. Added regression for concurrent password rotation during login and trusted
CLI password recovery. Real temporary nginx gateway verified login/logout, owner
auth_request, CSRF, Origin checks, no WWW-Authenticate and rejection of Basic Auth.

Production backup: `/data/CitVoiceStudio/backups/saas-before-admin-session-20261113-002418.sqlite3`.
Provisioned one admin with CLI; first password preserves the existing owner password,
not printed in Git/logs. Runtime image/code revision
`798f44414cf442976359409194631ed2eb3007c2`. GitHub fork updated.

Live HTTPS: anonymous root 302 to login, owner API 401, login page 200. Admin login
200 sets secure cookie, owner UI and deployment API 200, admin overview/plans 200;
logout makes admin me and owner API 401. Existing programmatic /public-api key still
returns health 200. Chrome form login/logout/login verified; left admin signed in.
One attempt to navigate root in Chrome timed out; root gate and authenticated 200
were verified separately over HTTPS. No credentials shown in screenshots.

Data after migration: users 0, plans 3, api_keys 0, usage_jobs 0, admin_users 1.
Plan-table SHA256 unchanged from backup baseline:
`fa81eab826e9d34ce00448c150bebbde9a19bf392c1af047c1c288ca5382b365`.
Login and admin screenshots in operator workspace. Old htpasswd retained on host
only for rollback; no longer mounted or used by runtime nginx.
