# CIT Voice Studio SaaS frontend

Vietnamese, dependency-free HTML/CSS/JS. Only files in this directory are changed.

## Serving

- Serve `index.html` at `/saas/` (and redirect or serve `/saas`).
- Serve `admin.html` at `/saas/admin`; `admin/index.html` is an identical directory-index fallback.
- Each HTML includes its own CSS and JS: no CDN, asset mount, bundler, or external font required.
- `app.js` and `style.css` are readable source copies. After editing, synchronize inline `<script>`/`<style>` in all three HTML files.
- Serve the same public `admin.html` at `/saas/admin/login` without Basic Auth. `/saas/admin` checks `/saas/api/admin-auth/me` before rendering protected content. Backend must enforce admin session authorization on `/saas/api/admin/*`; the frontend is not an authorization boundary.
- Admin cookies are backend-owned: Secure, HttpOnly, Path=/. They are separate from customer cookies. No live credentials or account provisioning are needed by this UI.
- User cookies are backend-owned: Path=/saas, Secure, HttpOnly, SameSite=Strict. Frontend uses same-origin fetch credentials and never stores passwords, keys, or sessions in localStorage.
- A CSP must permit the inline script/style (prefer deployment-generated SHA-256 hashes), audio `blob:` and same-origin connections.

## Integration assumptions

Uses the provided `/saas/api` contract. User CSRF comes from login/me; login and registration are exempt. Other user mutations require the token. Admin session/login responses use `{admin:{id,username,name,status},session_csrf}`. GET `/admin-auth/me` establishes frontend identity and CSRF; POST `/admin-auth/login` sends `{username,password}` without CSRF. Every other admin mutation includes `X-CSRF-Token`, JSON content type and the supplementary `X-Requested-With: CIT-SaaS`. POST `/admin-auth/logout` clears the session; POST `/admin-auth/password` sends `{current_password,new_password}`, expects `{ok:true,login_required:true}`, and returns to sign-in after the backend revokes all sessions.

The account/password screen is available from navigation (and `/saas/admin#account`). Admin API 401 responses redirect to login except for login and password-change requests. Login 401 responses show a readable credential error; password-change 401 responses display the server message and preserve the session so the current password can be corrected. Admin fetches explicitly send an empty `Authorization` header to override cached HTTP Basic credentials while `credentials: same-origin` retains the session cookie. The `next` query accepts only a single-leading-slash local path on the current origin; external URLs, protocol-relative URLs, backslashes, whitespace/control characters and login loops fall back to `/saas/admin`. Password inputs are hidden, bounded to 12–256 characters, cleared after submission, and never persisted or logged. Submit buttons prevent duplicate requests while busy.

The owner manually approves and assigns plans; no automatic payments or upgrades. All draft limits and prices are editable configuration, not sales quotes. Creating users requires selecting an enabled plan; opening public registration requires enabled Trial. Backend must enforce both gates.

Registration is closed until config explicitly returns `registration_enabled: true`. Admin settings writes PATCH `/admin/settings`; account creation writes POST `/admin/users` with active status. Plan expiry uses a local datetime input, converted to ISO UTC, or null for no expiry.

Registration is assumed to establish a session, like login; if the backend only creates an account, users should log in afterward. The backend owns validation, password policy, quota accounting, expiry, suspension, price publication, `sv_` secret generation, and default plan seeding (all Trial/Pro/Business disabled and draft; Trial price_minor=0, initial 1000 monthly and 500 per job; Pro/Business price_minor=null). Frontend never seeds or overwrites plans automatically. New plan IDs are entered explicitly. Plan IDs are sent as strings or null.

Voice lists may be an array or `{items: [...]}` / `{voices: [...]}`; entries may be strings or objects with id/voice_id and name/display_name. Generation is synchronous WAV binary; JSON responses produce readable errors, not fictitious success. Language is read-only and follows the selected voice.language, including the first voice; missing language blocks submission. Character counts use Unicode code points; server accounting is authoritative.

Usage renders the API's first page and identifies additional pages when `has_more` or `next_cursor` is present; pagination parameters are not specified in the contract. Summary numbers are never fabricated. Admin expiry expects `plan_expires_at` in user list records when set. Incoming timestamps support Unix seconds and ISO strings; expiry writes remain ISO UTC or null. No actual payment flow is claimed. Null prices stay unset; nonzero numeric fallback explicitly labels minor units rather than guessing currency decimals.

## Verification

`node --check app.js`

`node verify.mjs`

The dependency-free smoke test exercises DOM rendering and mocked API paths, closed registration, price states, cookie credentials, CSRF, and admin headers. It is not a real-browser layout test or live backend integration test. Mocked admin tests also cover session-first rendering, login success/errors and duplicate-submit protection, safe next destinations, password changes, logout, expiry redirects and CSRF on admin mutations. Live checks still needed when the backend contracts ship: public login routing, admin cookie attributes and revocation, supplied voice schema, WAV response, and quota/expiry enforcement. These checks do not use live credentials or create accounts.
