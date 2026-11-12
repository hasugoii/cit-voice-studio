#!/bin/sh
set -eu
mkdir -p /data/models /data/addons /data/gpu_venv
python - <<'PY'
from pathlib import Path
import re
from urllib.parse import urlsplit
from apps import deployment
origin = deployment.public_url()
if not origin:
    raise SystemExit('Gateway requires CIT_DEPLOYMENT_MODE=selfhost and CIT_PUBLIC_URL')
config = Path('/etc/nginx/nginx.conf.template').read_text()
config = config.replace('voice.apps.donomi.jp', urlsplit(origin).hostname)
config = config.replace(r'https://voice\.apps\.donomi\.jp', re.escape(origin))
config = config.replace('/public-api', deployment.api_prefix())
Path('/etc/nginx/nginx.conf').write_text(config)
PY
nginx -t
python -m apps.web_stream &
backend=$!
nginx -g 'daemon off;' &
gateway=$!
trap 'kill "$backend" "$gateway" 2>/dev/null || true' EXIT INT TERM
while kill -0 "$backend" 2>/dev/null && kill -0 "$gateway" 2>/dev/null; do sleep 2; done
exit 1
