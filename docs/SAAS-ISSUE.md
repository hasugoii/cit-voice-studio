# Manual SaaS accounts/plans — 2026-11-12

Baseline: one owner Basic Auth and one shared owner API key; no customer account,
per-user quota, plan editor or usage isolation. User requests SaaS admin and chose
manual approval/assignment, no automatic payment, all plan templates draft.

Thresholds before live deploy: anonymous owner admin 401; customer auth required;
passwords/keys never returned in lists; CSRF checks; tenant key/usage isolation;
suspension/expiry/revocation enforced; failed synthesis refunded; quota race cannot
overspend; plans cannot be assigned while draft; all three live templates remain
draft+disabled with signup off. Manual admin plan change and customer inference
verified in isolated test DB; live production probes must not create a hidden
customer or silently activate plans. Real user UI/admin UI must be inspected.
