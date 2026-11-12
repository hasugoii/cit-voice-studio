# Self-host deployment — 2026-11-12

Status: closed after source, isolated-runtime and live UI validation, 2026-11-13 JST.
Baseline: UI says Mạng LAN, shows Docker address and Windows/restart guidance;
API examples use management URL without /public-api and omit required API key.
Settings allow saving a port that breaks the fixed reverse-proxy upstream.

Change: explicit opt-in CIT_DEPLOYMENT_MODE=selfhost, configured HTTPS origin
CIT_PUBLIC_URL, public API prefix /public-api. Keep desktop defaults unchanged.
Do not infer trusted origin from arbitrary Host/X-Forwarded-* headers.

Success thresholds before implementation: desktop remote-access/server settings
tests pass; selfhost metadata shows configured HTTPS domain, no Docker IPs;
port mutation rejected 409; toggle immediately blocks/enables public API;
Swagger uses prefixed openapi endpoint and external server URL, API key required;
UI production build passes; real HTTPS API and both Japanese/Chinese TTS pass
after replacement with unchanged volume. UI live inspection must be distinguished
from source/build-only checks. No upstream push rights (viewerPermission READ).

Measured result: 84 backend tests (47 deployment/LAN/port plus 37 SaaS), 17 React
tests and dependency-free SaaS UI contract smoke checks pass. Live management
connection panel displays `https://voice.apps.donomi.jp` and `/public-api`, API
panel relabeled HTTPS. Real Swagger/OpenAPI points to the configured HTTPS Base
URL, requires key; missing key 401, key accepted 200, real WAV returned. Nhật/Trung
both report installed after replacement. Browser UI inspected; screenshot in
operator workspace. GitHub fork `hasugoii/cit-voice-studio`, default selfhost-vps;
runtime code/image revision `29a403c157ab9ed705ddc848ef073654fa904fa1`.
