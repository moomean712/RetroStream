#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

echo 'Downloading the latest RetroStream image...'
docker compose pull retrostream
docker compose up --detach retrostream

count=0
while [ "$count" -lt 60 ]; do
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' retrostream 2>/dev/null || true)
    [ "$status" = healthy ] && { echo 'RetroStream updated successfully. Your data and cache were preserved.'; exit 0; }
    [ "$status" = exited ] || [ "$status" = dead ] && break
    count=$((count + 1))
    sleep 2
done
echo "RetroStream did not become healthy (status: ${status:-unknown})." >&2
docker compose logs --tail=80 retrostream >&2
exit 1
