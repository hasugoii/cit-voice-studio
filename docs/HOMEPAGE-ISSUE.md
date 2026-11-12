# Public Donomi Voice homepage — 2026-11-13

Status: closed after source, isolated nginx and real desktop/mobile verification.

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

Results: 167 backend tests passed in the full runtime (no skips), React build and
17 tests passed; landing and SaaS UI contract scripts passed. Temporary nginx
verified anonymous homepage200, CSS200, sample audio Range206, studio302 without
admin/200 with admin, core management401 without session. Manual lead was accepted,
deduplicated and visible to admin, without creating users or activating plans.
That lead lived only in the disposable staging DB; no production test lead sent.

Real Chrome: sample playback observed (playing -> ended), CTA scrolled to request
form, private /studio loaded owner UI and admin inbox loaded. Initial 390px viewport
showed document width436 due to waveform intrinsic grid width. Fixed shrink/minmax
and reduced mobile bar gaps; remeasured width390 at390px and width320 at320px.
Versioned stylesheet URL v2 to invalidate the old cached layout. Viewport reset.

Runtime/backend release b14fa3a, frontend layout fix runtime image
`47ab221ce572b070ae45b9817520a7cd12314560`. Layout-only fix layered CSS+HTML over
the already-tested release image; future normal updater rebuilds all from Git.
Only voice service recreated. SQLite backup before migration:
`/data/CitVoiceStudio/backups/saas-before-homepage-20261113-004320.sqlite3`.
Post-deploy: users0,plans3,keys0,jobs0,admins1,requests0; three plans remain draft/off.
