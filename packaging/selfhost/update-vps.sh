#!/bin/sh
# Run as ubuntu from its Git checkout; Docker access uses sudo.
set -eu
umask 077
: "${COOLIFY_SERVICE_UUID:?Set the existing Coolify service UUID before updating}"
case "$COOLIFY_SERVICE_UUID" in *[!a-zA-Z0-9]*|'') echo 'Invalid service UUID' >&2; exit 1;; esac
cd "$(dirname "$0")/../.."
test -z "$(git status --porcelain)" || { echo 'Checkout has local changes; commit or stash first.' >&2; exit 1; }
git pull --ff-only origin selfhost-vps
revision=$(git rev-parse HEAD)
sudo docker build --label "org.opencontainers.image.revision=$revision" -f packaging/docker/Dockerfile -t cit-voice-studio:selfhost-vps .
sudo docker build --build-arg "SOURCE_REVISION=$revision" -t cit-voice-studio-gateway:selfhost-vps packaging/selfhost
service_path="/data/coolify/services/$COOLIFY_SERVICE_UUID"
sudo test -f "$service_path/docker-compose.yml"
sudo docker compose --project-directory "$service_path" -f "$service_path/docker-compose.yml" up -d --force-recreate --no-deps voice
echo "Updated source/image to $revision; verify HTTPS health, admin and tenant APIs before declaring release complete."
