# Manual SaaS accounts/plans — 2026-11-12

Status: closed for manual-service scope after verification, 2026-11-13 JST.

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

Result: all 37 SaaS tests pass; combined backend checks 84 pass, React 17 pass.
An isolated container using actual model inference created a test account and
personal API key, returned a 153798-byte WAV, charged exactly 25 characters, and
left zero reserved characters. It used its own SQLite database and was removed;
no test customer or plan activation was created in production.

Live HTTPS: user page 200, anonymous admin and user me 401, owner authenticated
admin 200. Three templates remain disabled+draft, registration false, users/jobs
zero. Owner web user/admin UI inspected in real Chrome. Existing owner inference
returned a 230598-byte WAV. Current active engine is VieNeu; Nhật/Trung Kokoro
packs remain installed but only one engine is active at a time.

Manual billing and draft plans delivered as requested. Automated payment,
password reset/email verification, queued jobs and multi-model concurrency are
not part of this release. Validation scope/advisories in SELFHOST-DATA-GAPS.md.
