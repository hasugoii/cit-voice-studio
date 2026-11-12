# Donomi Voice public homepage

- `/`: public marketing page. Brand approved by owner: Donomi Voice.
- `/saas/`: customer portal (manual account approval remains in effect).
- `/saas/admin`: owner administration with administrator session.
- `/studio`: private owner engine UI, previously served at root. Bookmarks to `/`
  now open the homepage; desktop mode still serves the original app at `/`.

Edit `apps/landing_static/homepage.html`, `homepage.css`, `homepage.js`; rebuild
images and redeploy using `packaging/selfhost/update-vps.sh`. HTTPS canonical and
API example origin use `CIT_PUBLIC_URL`. Fonts are local Inter subsets, with the
license included in `FONT-LICENSE.txt`; no third-party tracking or font service.

Listen samples are actual prerecorded Vietnamese preset inference (Hải Đăng and
Trúc Ly). Provenance, transcripts and hashes are in HOMEPAGE-SAMPLES.json. They
do not expose the owner key or permit anonymous synthesis. Regenerate samples only
from authorized preset voices; don't publish private customer/owner cloned voices.

The public request form stores name/email/purpose in `access_requests` in the
existing SQLite volume, for owner review under Yêu cầu tài khoản. No email is sent,
no account is created and no plan is activated automatically. Requests use exact
Origin validation, input bounds, a honeypot, scoped throttling and 24-hour email
deduplication with generic acknowledgement. Contact data is visible only to admin.
The admin marks requests new/reviewed/closed and creates accounts separately after
agreement. Do not interpret reviewed as a payment or subscription approval.

Pricing is intentionally not published while all plans are drafts. The site makes
no customer-count, uptime or speed promises. Shared-model and manual-onboarding
limits are explained in FAQ. Keep those statements aligned with real service state.

Checks: `node apps/landing_static/verify.mjs`, SaaS frontend verification, Python
homepage/auth/tenant tests, public audio Range responses and real browser desktop /
mobile inspection. Public assets are an explicit whitelist; add new filenames to
the backend whitelist rather than serving arbitrary files from the application.
