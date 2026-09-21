#!/bin/sh
set -eu

cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

line='--------------------------------------------------'
printf '%s\nRetroStream Docker Setup\n%s\n\n' "$line" "$line"

if ! command -v docker >/dev/null 2>&1; then
    cat <<'EOF'
Docker is not installed.

Windows/macOS: install Docker Desktop.
Linux: install Docker Engine and the Docker Compose plugin using Docker's
official instructions. Then run this installer again.
EOF
    exit 1
fi
printf 'Docker .............. OK\n'
if ! docker compose version >/dev/null 2>&1; then
    printf '%s\n' 'Docker Compose is missing. Install the Docker Compose plugin, then run this installer again.' >&2
    exit 1
fi
printf 'Docker Compose ...... OK\n'
if ! docker info >/dev/null 2>&1; then
    printf '%s\n' 'Docker is installed but is not running (or your account cannot use it). Start Docker and try again.' >&2
    exit 1
fi

detected=$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')
if [ -z "$detected" ]; then
    detected=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
current=$(sed -n 's/^RETROSTREAM_HOSTNAME=//p' .env 2>/dev/null | tail -n 1 || true)
current_web=$(sed -n 's/^RETROSTREAM_WEB_PORT=//p' .env 2>/dev/null | tail -n 1 || true)
current_stream=$(sed -n 's/^RETROSTREAM_STREAMING_PORT=//p' .env 2>/dev/null | tail -n 1 || true)
default=${current:-$detected}
web_port=${current_web:-8780}
streaming_port=${current_stream:-8781}
printf '\nDetected LAN address: %s\n\n' "${detected:-not found}"
printf 'How will your retro PCs reach this server?\n'
while :; do
    printf '[%s]: ' "$default"
    IFS= read -r entered
    host=${entered:-$default}
    case "$host" in
        ''|*://*|*/*|*:*|*[!A-Za-z0-9.-]*)
            printf '%s\n' 'Enter an IPv4 address or LAN DNS name only (for example 192.168.1.50).'
            ;;
        *) break ;;
    esac
done

tmp=.env.retrostream.tmp
if [ -f .env ]; then
    awk '!/^RETROSTREAM_HOSTNAME=|^RETROSTREAM_WEB_PORT=|^RETROSTREAM_STREAMING_PORT=/' .env > "$tmp"
else
    : > "$tmp"
fi
{
    printf 'RETROSTREAM_HOSTNAME=%s\n' "$host"
    printf 'RETROSTREAM_WEB_PORT=%s\n' "$web_port"
    printf 'RETROSTREAM_STREAMING_PORT=%s\n' "$streaming_port"
} >> "$tmp"
mv "$tmp" .env

printf '\nStarting RetroStream...\n'
docker compose pull retrostream
docker compose up --detach retrostream

status=unknown
count=0
while [ "$count" -lt 60 ]; do
    status=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' retrostream 2>/dev/null || true)
    [ "$status" = healthy ] && break
    [ "$status" = exited ] || [ "$status" = dead ] && break
    count=$((count + 1))
    sleep 2
done

if [ "$status" != healthy ]; then
    printf '\nRetroStream did not become healthy (status: %s). Recent logs:\n' "$status" >&2
    docker compose logs --tail=80 retrostream >&2
    exit 1
fi

code=$(docker compose logs --no-color retrostream 2>/dev/null | grep -Eo '[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}' | tail -n 1 || true)
printf '\n%s\nRetroStream is running!\n\nOpen:\n\nhttp://%s:%s/setup\n' "$line" "$host" "$web_port"
if [ -n "$code" ]; then
    printf '\nFirst-run setup code:\n\n%s\n' "$code"
else
    printf '\nNo new setup code was found. Setup may already be complete.\nRun "docker compose logs retrostream" to inspect startup messages.\n'
fi
printf '\nStreaming port: %s\n\nYour data and playlists are stored safely and survive container updates.\n%s\n' "$streaming_port" "$line"
