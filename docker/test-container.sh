#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

echo 'Checking container health and bundled runtime...'
test "$(docker inspect --format '{{.State.Health.Status}}' retrostream)" = healthy
docker compose exec -T retrostream python -c "import os,socket,urllib.request,yt_dlp; p=int(os.environ['RETROSTREAM_WEB_PORT']); s=int(os.environ['RETROSTREAM_STREAMING_PORT']); assert urllib.request.urlopen(f'http://127.0.0.1:{p}/healthz').read()==b'{\"status\":\"ok\"}'; [socket.create_connection(('127.0.0.1', port), 3).close() for port in (p,s)]"
docker compose exec -T retrostream deno --version
docker compose exec -T retrostream yt-dlp --version
docker compose exec -T retrostream sh -c "ffmpeg -hide_banner -encoders 2>&1 | grep -E 'wmav2|wmv1|wmv2'"
docker compose exec -T retrostream sh -c "ffmpeg -hide_banner -muxers 2>&1 | grep -E '[[:space:]]asf[[:space:]]'"

echo 'Encoding synthetic WMA, WMV1, and WMV2 samples...'
docker compose exec -T retrostream sh -c '
set -eu
work=$(mktemp -d /tmp/retrostream-media-test.XXXXXX)
trap '\''rm -rf "$work"'\'' EXIT
ffmpeg -hide_banner -loglevel error -y -f lavfi -i testsrc2=size=320x240:rate=25 -f lavfi -i sine=frequency=440:sample_rate=44100 -t 1 -c:v mpeg4 -c:a pcm_s16le "$work/source.mkv"
ffmpeg -hide_banner -loglevel error -y -i "$work/source.mkv" -map 0:a:0 -c:a wmav2 -ar 44100 -ac 2 -b:a 128k -vn -f asf "$work/audio.wma"
ffmpeg -hide_banner -loglevel error -y -i "$work/source.mkv" -map 0:a:0 -c:a wmav2 -b:a 128k -map 0:v:0 -c:v wmv1 -pix_fmt yuv420p -f asf "$work/low.wmv"
ffmpeg -hide_banner -loglevel error -y -i "$work/source.mkv" -map 0:a:0 -c:a wmav2 -b:a 128k -map 0:v:0 -c:v wmv2 -pix_fmt yuv420p -f asf "$work/standard.wmv"
test -s "$work/audio.wma" && test -s "$work/low.wmv" && test -s "$work/standard.wmv"
'
echo 'Container runtime and synthetic media checks passed.'
