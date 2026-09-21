# Architecture and implementation plan

RetroStream is a single-process Python application. FastAPI provides typed HTTP
routes and Jinja renders HTML forms; SQLite's standard-library driver provides
short transactions, foreign keys, WAL, and versioned SQL migrations. No external
queue or frontend build is needed.

The v1 refinement added schema migration 2 for a single administrator and revocable
sessions, safe redirect-back form behavior, separate audio/video controls, WPL,
and a compact XP-style interface. The media/cache/streaming architecture remains intact.

Media identity is independent of cache identity. Playlist slugs are assigned once.
Representations are keyed by media ID and profile, with one active Audio profile
and one active Video profile per media item. A replacement is published and
validated before the superseded file is retired. Direct and playlist protection
applies to the active profile of that media type. If playlists request conflicting
qualities, the latest successfully prepared explicit request wins; all playlists
share that one physical representation until another request succeeds.
One process owns the cache: a lock coordinates generation, eviction, and stream
leases; a bounded worker queue handles expensive work. Multiple ASGI workers are
unsupported. Jobs survive restart; interrupted jobs are marked failed for retry.
Completed cache files are atomically renamed, then recorded; startup reconciles
files with database state and removes incomplete work files.

Streaming lives behind its own router. Ordinary HTTP range delivery serves
complete seekable ASF files. The implemented MMSH VOD adapter handles Describe,
Play, framed ASF delivery and stream-time seeking; it is tested independently
with FFmpeg. See protocol.md for boundaries. Real-client results are recorded
separately in validation.md. Docker is a packaging layer around this architecture.

## Module map

| Module | Responsibility |
| --- | --- |
| config.py | Validated TOML/environment settings |
| database/ | SQLite transactions, schema migration and indexes |
| library.py / metadata.py | Stable IDs, metadata, playlist membership/order |
| youtube.py / process.py | Canonical source inputs and owned subprocess lifetimes |
| jobs.py / service.py | Durable queue, orchestration, maintenance and retries |
| transcoder.py / cache.py | Explicit FFmpeg profiles, atomic storage, pins and LRU |
| streaming/ | ASF parsing, ASX/WPL, friendly URL aliases, HTTP ranges and MMSH frames |
| api/ / frontend/ | JSON and plain HTML form adapters over the same service |
| auth.py / security.py / app.py | Passwords, sessions, CSRF, safe returns, Host validation and routing |
| main.py | Single-instance lock, two listeners, signals and structured logs |

Shutdown stops accepting work and terminates owned subprocess groups. Container
shutdown signals the foreground process directly. Queued/interrupted
jobs become Failed on the next start and can be retried. Cache reconstruction
validates bounded ASF headers/indexes before marking representations complete.
No external program output containing signed URLs or cookies is retained.
