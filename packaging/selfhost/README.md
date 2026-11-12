# VPS / Coolify gateway

This directory is versioned with the application. It adds Basic Auth for the
management UI and app-key auth for `/public-api`. Deploy only behind HTTPS.
Backend stays loopback-only; no direct host port 8001 should be published.

Build from repository root:

```bash
docker build -f packaging/docker/Dockerfile -t cit-voice-studio:selfhost-vps .
docker build -t cit-voice-studio-gateway:selfhost-vps packaging/selfhost
```

`selfhost-vps` is the local image tag used by the installed Coolify service.
Record the actual Git commit at deployment. These are local images, not registry pulls.

Copy `compose.yaml` into a Coolify Compose service; set the domain on service
`voice` to `https://YOUR-DOMAIN:8080` (8080 is the internal gateway port, public
URL remains HTTPS 443). Change `CIT_PUBLIC_URL` to the same HTTPS origin.
`SERVICE_FQDN_VOICE_8080` is interpreted by Coolify; on plain Docker Compose it
does not itself create DNS or TLS and requires your own reverse proxy.

Create `/data/cit-voice-auth/htpasswd` on the VPS with a compatible password hash
using a trusted password tool; never commit credentials. The gateway reads it
from the read-only mount `/run/cit-auth/htpasswd`. Keep username/password in a
secret manager. All model/addon/runtime/settings/history files persist in the
named `/data` volume. Existing installations must copy `/app/gpu_venv` into
`/data/gpu_venv` before first migration to this image to preserve interpreter paths.

Deployment configuration:

- `CIT_DEPLOYMENT_MODE=selfhost`
- `CIT_PUBLIC_URL=https://YOUR-DOMAIN` (DNS and Coolify route must match)
- `CIT_PUBLIC_API_PREFIX=/public-api`
- `PORT=8001` (container-managed, cannot be changed from the web UI)

Gateway renders its hostname, allowed browser Origin and public prefix at startup.
Swagger lives at `$CIT_PUBLIC_URL/public-api/docs`; use the API key from Settings
→ API qua HTTPS → Khóa API. Key rotation/toggle is enforced by the backend;
management Basic Auth is separate. Supported models share one active instance.

## Update your fork

```bash
git switch selfhost-vps
git pull --ff-only origin selfhost-vps
# Rebuild both images as above, then Redeploy this service in Coolify.
```

## Merge upstream changes

```bash
git fetch upstream
git switch selfhost-vps
git merge upstream/main
# Resolve conflicts, run tests/build, then push origin selfhost-vps.
```

Do not reset this branch to upstream/main: it would remove selfhost changes.
Do not remove the named volume during updates. Back up volume before major changes.
README API examples for the installed service are in the operator workspace;
the web UI now generates external examples using configured domain and API key.

## Installed VPS update command

```bash
cd /home/ubuntu/cit-voice-selfhost-repo
env COOLIFY_SERVICE_UUID=akk7ydzazhn2fkb8svt0zmsr sh packaging/selfhost/update-vps.sh
```

This service-specific command pulls the fork branch, rebuilds both local images and
recreates only the voice service. It does not change firewall, Docker daemon, or
remove volumes. Domain/environment changes must first be saved in Coolify.
