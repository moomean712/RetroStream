# Configuration

Pass `--config /path/retrostream.toml` or set `RETROSTREAM_CONFIG`. The file is TOML
with top-level keys (no section header). `RETROSTREAM_<UPPERCASE_KEY>` overrides
each file value. Without a file, built-in defaults apply. Invalid values fail
startup. Settings in the UI are read-only; change the file and restart.

| Setting | Default | Meaning |
| --- | --- | --- |
| `bind` | `127.0.0.1` | Explicit listen address, shared by both TCP listeners |
| `hostname` | `localhost` | DNS name or IPv4 address used in permanent URLs; no scheme/port |
| `web_port` | `8780` | Setup/login, management UI, JSON API, ASX/WPL, and fallback media routes |
| `streaming_port` | `8781` | Media-only listener used by ASX refs; may equal web_port |
| `data_dir` | `data` | SQLite database and single-instance lock |
| `cache_dir` | `data/cache` | Completed representations and isolated temporary work |
| `max_cache_bytes` | `21474836480` | 20 GiB completed-cache budget (soft, not a filesystem quota) |
| `retention_days` | `30` | Unused age for eligible cache expiration |
| `cleanup_threshold` | `0.90` | Size fraction at which LRU pressure cleanup begins |
| `cleanup_target` | `0.75` | Target fraction after pressure cleanup |
| `cleanup_interval` | `3600` | Seconds between automatic jobs; also cleanup after generation |
| `default_audio` | `audio-standard` | Representation for permanent `/audio` refs |
| `default_video` | `video-standard` | Representation for permanent `/video` refs |
| `max_transcodes` | `2` | Worker count; imports/cleanup share these workers |
| `max_streams` | `16` | Active media requests, including preparation waiters |
| `preparation_timeout` | `1800` | Seconds a media request waits for a queued cache job |
| `subprocess_timeout` | `7200` | Timeout per yt-dlp or FFmpeg subprocess |
| `max_import_entries` | `1000` | Maximum entries per source playlist; use smaller source playlists for more |
| `ffmpeg` | `ffmpeg` | Executable name in PATH or absolute administrator-configured path |
| `js_runtime` | `deno` | Deno recommended; node/quickjs/bun accepted subject to yt-dlp requirements |
| `debug` | `false` | Debug level and HTTP access logs |

Use absolute `data_dir` and `cache_dir` in a service. Relative paths resolve from
the working directory. Changing a cache directory does not move files; stop the
service, copy it, update permissions/configuration and restart. Never share a
cache between independent instances or alter it while the service is running.

The 8780/8781 defaults apply to new configurations. Existing files that explicitly
set the former 8080/8081 ports remain unchanged after upgrade. Dynamic playlists
use the current configured ports; download fresh ASX snapshots after changing them.

`hostname` also restricts web Host headers against DNS rebinding. `localhost`
and `127.0.0.1` are accepted for local diagnostics. Access the admin UI using the
configured hostname; a different LAN IP/name gets a 400 until configured.
The media-only port doesn't carry admin endpoints. IPv6 bind addresses can be
used, but generating IPv6-literal URLs is not implemented; use a DNS hostname.

| Profile | Audio | Video | Container |
| --- | --- | --- | --- |
| audio-standard | WMAv2, 44.1 kHz stereo, 128 kbps | None | ASF / .wma |
| audio-high | WMAv2, 44.1 kHz stereo, 192 kbps | None | ASF / .wma |
| video-low / Low (Legacy) | WMAv2 128 kbps | WMV1, 320×240, 450 kbps | ASF / .wmv |
| video-standard | WMAv2 128 kbps | WMV2, 640×360, 900 kbps | ASF / .wmv |
| video-high | WMAv2 192 kbps | WMV2, 854×480, 1500 kbps | ASF / .wmv |

Video uses 25 fps, YUV420, square pixels and a two-second GOP. Images are scaled
proportionally and padded. Some old hardware may need Low. Video without an audio
stream, or audio-only sources requested in Video mode, fail explicitly in v1.
Changing encoder settings in code requires clearing affected unpinned objects
(unpin protected ones deliberately first); profile names are the cache version keys.

## Storage behavior

Completed files live at `{cache_dir}/{internal-media-id}/{profile}.wma|wmv`.
There is one file per media/profile across all playlists. Sources and incomplete
outputs live under `.work/rs-*` and are removed after jobs or during restart.

Cleanup removes expired eligible entries, then oldest eligible entries under
size pressure; ties use media ID and profile for deterministic ordering. Explicit
pins and every playlist pin are combined. Releasing one pin doesn't cancel others.
In-flight generation and active delivery leases are excluded from all eviction.
Stats distinguish CACHED/PINNED/UNCACHED/CACHING/FAILED; pin intent remains visible
even when an object is uncached or failed.

The limit is deliberately soft: pins and active delivery can exceed it, and
temporary downloads/transcodes consume additional space. Allow headroom of at
least one source plus output per worker. A filesystem quota can impose a hard
disk bound, but full-disk jobs will fail. Library metadata remains in SQLite.
Manual cache clearing uses the same protections. Clearing playlist cache affects
shared physical representations in other playlists unless protected there.

`last_accessed` is refreshed by media requests/cache hits. `last_played` means a
successful delivery request, not proof that someone listened. History expires
after 90 days; aggregate request counts and last access timestamps remain.
