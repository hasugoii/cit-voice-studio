# CIT Voice Studio SaaS frontend

Vietnamese, dependency-free HTML/CSS/JS. Only files in this directory are changed.

## Serving

- Serve `index.html` at `/saas/` (and redirect or serve `/saas`).
- Serve `admin.html` at `/saas/admin`; `admin/index.html` is an identical directory-index fallback.
- Each HTML includes its own CSS and JS: no CDN, asset mount, bundler, or external font required.
- `app.js` and `style.css` are readable source copies. After editing, synchronize inline `<script>`/`<style>` in all three HTML files.
- Backend/nginx must enforce owner Basic Auth on **both** admin page and `/saas/api/admin/*`. The frontend is not an authorization boundary.
- User cookies are backend-owned: Path=/saas, Secure, HttpOnly, SameSite=Strict. Frontend uses same-origin fetch credentials and never stores passwords, keys, or sessions in localStorage.
- A CSP must permit the inline script/style (prefer deployment-generated SHA-256 hashes), audio `blob:` and same-origin connections.

## Integration assumptions

Uses the provided `/saas/api` contract. User CSRF comes from login/me; login and registration are exempt. Other user mutations require the token. Admin mutations carry `X-Requested-With: CIT-SaaS` and JSON content type.

The owner manually approves and assigns plans; no automatic payments or upgrades. All draft limits and prices are editable configuration, not sales quotes. Creating users requires selecting an enabled plan; opening public registration requires enabled Trial. Backend must enforce both gates.

Registration is closed until config explicitly returns `registration_enabled: true`. Admin settings writes PATCH `/admin/settings`; account creation writes POST `/admin/users` with active status. Plan expiry uses a local datetime input, converted to ISO UTC, or null for no expiry.

Registration is assumed to establish a session, like login; if the backend only creates an account, users should log in afterward. The backend owns validation, password policy, quota accounting, expiry, suspension, price publication, `sv_` secret generation, and default plan seeding (all Trial/Pro/Business disabled and draft; Trial price_minor=0, initial 1000 monthly and 500 per job; Pro/Business price_minor=null). Frontend never seeds or overwrites plans automatically. New plan IDs are entered explicitly. Plan IDs are sent as strings or null.

Voice lists may be an array or `{items: [...]}` / `{voices: [...]}`; entries may be strings or objects with id/voice_id and name/display_name. Generation is synchronous WAV binary; JSON responses produce readable errors, not fictitious success. Language is read-only and follows the selected voice.language, including the first voice; missing language blocks submission. Character counts use Unicode code points; server accounting is authoritative.

Usage renders the API's first page and identifies additional pages when `has_more` or `next_cursor` is present; pagination parameters are not specified in the contract. Summary numbers are never fabricated. Admin expiry expects `plan_expires_at` in user list records when set. Incoming timestamps support Unix seconds and ISO strings; expiry writes remain ISO UTC or null. No actual payment flow is claimed. Null prices stay unset; nonzero numeric fallback explicitly labels minor units rather than guessing currency decimals.

## Verification

`node --check app.js`

`node verify.mjs`

The dependency-free smoke test exercises DOM rendering and mocked API paths, closed registration, price states, cookie credentials, CSRF, and admin headers. It is not a real-browser layout test or live backend integration test. Live checks still needed: nginx protection, cookie attributes, supplied voice schema, WAV response, and quota/expiry enforcement.
