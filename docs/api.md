# Internal HTTP API

The API and HTML forms call the same service layer and persistent job queue.
Essential UI actions use ordinary POST forms, so the browser doesn't need fetch,
XHR or JavaScript. JSON routes are available for LAN scripts and future clients.
`/docs` exposes interactive OpenAPI and `/openapi.json` exposes the schema.

All `/api` routes require an administrator session. Mutation requests additionally
require the signed CSRF cookie and `X-CSRF-Token`; CSRF tokens expire after 12 hours.
HTML forms send the token as `csrf`. JSON clients should retain the cookie jar.

Example on the server (Python performs JSON parsing, not string interpolation):

```sh
RETROSTREAM_URL=http://localhost:8780
read -r -p 'Administrator user: ' RETROSTREAM_USER
read -r -s -p 'Administrator password: ' RETROSTREAM_PASSWORD; printf '\n'
curl -fsS -c /tmp/retrostream-cookies "$RETROSTREAM_URL/login" -o /tmp/retrostream-login.html
RETROSTREAM_LOGIN_CSRF=$(python3 -c 'import re; print(re.search(r"name=\"csrf\" value=\"([^\"]+)",open("/tmp/retrostream-login.html").read()).group(1))')
curl -fsS -b /tmp/retrostream-cookies -c /tmp/retrostream-cookies \
  --data-urlencode "csrf=$RETROSTREAM_LOGIN_CSRF" \
  --data-urlencode "username=$RETROSTREAM_USER" \
  --data-urlencode "password=$RETROSTREAM_PASSWORD" \
  --data-urlencode 'return_to=/' "$RETROSTREAM_URL/login" -o /dev/null
unset RETROSTREAM_PASSWORD
RETROSTREAM_CSRF=$(curl -fsS -b /tmp/retrostream-cookies -c /tmp/retrostream-cookies "$RETROSTREAM_URL/api/csrf" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["csrf_token"])')
curl -fsS -b /tmp/retrostream-cookies -H "X-CSRF-Token: $RETROSTREAM_CSRF" \
  -H 'Content-Type: application/json' --data '{"name":"90s Mix"}' \
  "$RETROSTREAM_URL/api/playlists"
```

Use the returned `id` for API mutations and returned `slug` for ASX links. The
following table's `{pid}`, `{mid}` and `{jid}` are those opaque identifiers.

| Method/path | Body or result |
| --- | --- |
| GET `/api/media?offset=0&limit=100` | Library metadata; limit capped at 500 |
| POST `/api/media/import` | `{ "urls": ["https://youtu.be/abcdefghijk"], "playlist_id": "…" }`; playlist_id optional; 202 job_id |
| POST `/api/media/{mid}/refresh` | Retry metadata; 202 job_id |
| GET `/api/playlists` | Names, immutable IDs/slugs, item counts |
| POST `/api/playlists` | `{ "name": "My playlist" }`; 201 playlist |
| GET `/api/playlists/{pid}` | Playlist, ordered items and pinned profiles |
| PATCH `/api/playlists/{pid}` | `{ "name": "New name" }`; slug unchanged |
| DELETE `/api/playlists/{pid}?confirm=true` | Remove playlist/membership/pin refs, not library/cache |
| POST `/api/playlists/{pid}/items` | `{ "media_ids": ["…", "…"] }`; append, deduplicate |
| DELETE `/api/playlists/{pid}/items/{mid}` | Remove local membership |
| POST `/api/playlists/{pid}/reorder` | `{ "media_ids": ["…", "…"] }`; must contain each item exactly once |
| POST `/api/playlists/{pid}/cache` | `{ "profile": "audio-standard" }`; 202 job_ids |
| POST `/api/playlists/{pid}/pin` | `{ "profile": "video-standard", "enabled": true }` |
| POST `/api/media/{mid}/cache` | `{ "profile": "audio-high" }`; 202 job_id |
| POST `/api/media/{mid}/pin` | `{ "profile": "audio-standard", "enabled": false }`; only explicit item pin changes |
| GET `/api/cache` | Storage totals and all representation states/protection |
| POST `/api/cache/cleanup` | Queue expiration/LRU cleanup; 202 job_id |
| POST `/api/cache/clear` | `{ "kind": "audio", "confirm": true }`; kind audio/video/all; 202 job_id |
| GET `/api/jobs` | Latest 100 jobs, Queued/Running/Completed/Failed and safe error text |
| POST `/api/jobs/{jid}/retry` | Retry a failed job; 202 new job_id |
| GET `/api/status` | Counts, disk, active requests/jobs, dependencies, recent failures |
| GET `/api/settings` | Effective file/environment configuration; no secrets |

Source limits: 1–100 URLs per request, at most `max_import_entries` entries from
each remote playlist. A watch URL with a `list` query still imports a single video;
use `/playlist?list=…` for the playlist. Unsupported/private/live/protected items
are not bypassed. Partial imports retain successes and mark the job Failed with
a count; valid unavailable video IDs retain placeholder records for retry.

Missing/expired login returns 401 for API routes. Known validation errors return
400, unknown resources 404, bad CSRF 403, invalid
typed payloads 422, oversized admin bodies 413, stream saturation/preparation
failure 503 with Retry-After. Media GET/HEAD routes do not require a cookie.
Successful play history is a delivery-request metric, not client listening telemetry.

ASX: `GET /playlists/{slug}/audio.asx` and `/video.asx`. Add `?download=1`
for a file snapshot. Optional WPL uses the same paths with `.wpl`. Media: `GET`
or `HEAD` `/media/{mid}/audio`, `/video`, a fixed profile such as `/audio-high`,
or the cosmetic filename alias appended by WPL. Playlist and media delivery routes
remain unauthenticated for legacy players. Keep hostnames/slugs stable; re-fetching
a permanent playlist URL gives the current order.
