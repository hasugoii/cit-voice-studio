# Public Donomi Voice homepage — 2026-11-13

Baseline: root requires admin login and serves owner engine UI; customer portal
exists at /saas, signup closed, three plans draft/disabled. No public landing page,
samples or request-access inbox. Owner approved brand Donomi Voice and homepage.

Plan: public / homepage, owner engine moves to /studio (session remains required),
customer/admin URLs unchanged. Real prerecorded preset-voice samples, no anonymous
generation endpoint. Manual access-request inbox, no automatic account activation.
No invented prices, customers, throughput, uptime or simultaneous-model promises.

Criteria set before deployment: anonymous homepage/assets/audio200, studio redirects
withoutadmin and returns200 withsession; APIs/admin still401 withoutauth; false
Origin rejected; form validated, throttled/deduplicated and creates no users or
plan changes; lead inbox role/CSRF checks; desktop root remains original app.
Responsive desktop/mobile UI and audio playback tested in real browser. New leads
are sensitive contact data; no third-party tracking/mail integration.
