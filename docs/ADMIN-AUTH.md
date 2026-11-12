# Administrator login — 2026-11-13

- Login: `/saas/admin/login`; admin dashboard `/saas/admin`; owner engine UI `/studio`. Public `/` is the marketing homepage.
- Dedicated admin account (`admin_users`) and sessions (`admin_sessions`), separate
  from customer user/plan/keys. Creating a customer never grants administrator role.
- First owner is provisioned only from the trusted VPS CLI, never a public setup URL.
  `python -m apps.admin_cli bootstrap --username admin` asks for the password.
- Passwords salted+scrypt; session tokens hashed at rest. Secure, HttpOnly,
  SameSiteStrict host-only cookie at `/`, expires after 12 hours. New token on login.
- Admin mutations require CSRF; browser Origin must match configured HTTPS domain.
  Keys, Basic Authorization, spoofed forwarding headers and loopback do not bypass
  session checks. nginx `auth_request` fails closed if session validation fails.
- Logout revokes the current session. Password change verifies old password and
  revokes every admin session. Login rechecks the password hash transactionally
  before creating a session so a concurrent reset cannot resurrect old credentials.
- Trusted recovery: container CLI `python -m apps.admin_cli reset-password --username
  admin`; prompts privately and revokes all sessions. No public forgot-password
  workflow or email delivery is configured. Customer password handling stays separate.
- Owner API key `/public-api` and tenant keys `/saas/api` remain programmatic auth;
  they never grant owner management. Admin session cookie is needed only for owner UI.
- DB upgrade is additive; existing plans, users and usage are not reset. Back up the
  SQLite file with online backup before migration. Old htpasswd may be retained on
  host for rollback but is unused and not mounted by the new compose.
