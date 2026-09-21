#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

stamp=$(date +%Y%m%d-%H%M%S)
destination="backups/retrostream-$stamp"
mkdir -p "$destination"

was_running=$(docker inspect --format '{{.State.Running}}' retrostream 2>/dev/null || true)
restore_service() {
    [ "$was_running" = true ] && docker compose start retrostream >/dev/null
}
trap restore_service EXIT INT TERM

echo 'Pausing RetroStream briefly for a consistent SQLite backup...'
[ "$was_running" = true ] && docker compose stop retrostream >/dev/null
docker compose cp retrostream:/data/. "$destination/data"
if [ "${1:-}" = "--include-cache" ]; then
    docker compose cp retrostream:/cache/. "$destination/cache"
fi
restore_service
trap - EXIT INT TERM

echo "Backup complete: $destination"
echo 'Keep this folder private; it contains administrator and session state.'
