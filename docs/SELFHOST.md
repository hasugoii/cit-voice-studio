# Self-host mode for VPS

This branch adds an opt-in mode without changing desktop defaults:

```dotenv
CIT_DEPLOYMENT_MODE=selfhost
CIT_PUBLIC_URL=https://voice.apps.donomi.jp
CIT_PUBLIC_API_PREFIX=/public-api
PORT=8001
```

The origin must be HTTPS, without user info, path, query or fragment. Deployment
metadata always uses explicit configuration, never client-controlled forwarded
headers. Settings show domain/public API URL rather than Docker interface IPs.
API toggle takes effect immediately; there is no listener restart requirement.
Internal port is container-managed; web attempts to change it return 409.
Existing persisted desktop port preferences do not override the container port.

Requires the session-authenticated same-container nginx gateway in the sibling
`deployments/cit-voice-studio` directory in the VPS workspace. Backend binds only
loopback; gateway validates administrator session with auth_request and proxies with local
headers for management. External API prefix preserves forwarded classification
and passes API key to the app. It exposes only six inference/status routes and
four documentation routes. Other prefixed routes return 404. Do not forward
untrusted requests to management using local headers without authentication.

Swagger fetches OpenAPI via the public prefix, declares the external HTTPS server
URL and requires API key for inference requests. Examples use public Base URL and
environment secret VOICE_API_KEY. Docs are public; management routes/keys/history
remain private. Desktop retains its original listener, LAN UI and port settings.

Gateway template derives server name and allowed browser Origin from the same
CIT_PUBLIC_URL at startup. Changing a domain requires matching DNS/Coolify domain
and environment, then redeploy. The image no longer needs a hard-coded Host fix.
This is a single-owner server with one shared active model and one API key,
not a multitenant service. No GPU support is implied by deployment mode.
