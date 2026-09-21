BEGIN IMMEDIATE;
CREATE TABLE media (
 id TEXT PRIMARY KEY, youtube_id TEXT NOT NULL UNIQUE, original_url TEXT NOT NULL,
 youtube_title TEXT NOT NULL, title TEXT NOT NULL, artist TEXT, album TEXT,
 album_artist TEXT, year TEXT, genre TEXT, track_number TEXT, uploader TEXT,
 duration REAL, thumbnail_url TEXT, added REAL NOT NULL, last_played REAL,
 last_accessed REAL, extracted REAL, request_count INTEGER NOT NULL DEFAULT 0,
 error TEXT
);
CREATE TABLE playlists (
 id TEXT PRIMARY KEY, slug TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 created REAL NOT NULL
);
CREATE TABLE playlist_items (
 playlist_id TEXT REFERENCES playlists(id) ON DELETE CASCADE,
 media_id TEXT REFERENCES media(id) ON DELETE CASCADE, position INTEGER NOT NULL,
 PRIMARY KEY (playlist_id, media_id)
);
CREATE INDEX playlist_order ON playlist_items(playlist_id, position);
CREATE TABLE playlist_pins (
 playlist_id TEXT REFERENCES playlists(id) ON DELETE CASCADE,
 profile TEXT NOT NULL, PRIMARY KEY(playlist_id, profile)
);
CREATE TABLE cache_entries (
 media_id TEXT REFERENCES media(id) ON DELETE CASCADE, profile TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'UNCACHED' CHECK(state IN ('UNCACHED','CACHING','CACHED','FAILED')),
 pinned INTEGER NOT NULL DEFAULT 0, size INTEGER NOT NULL DEFAULT 0,
 last_accessed REAL NOT NULL, error TEXT, PRIMARY KEY(media_id, profile)
);
CREATE INDEX cache_lru ON cache_entries(last_accessed);
CREATE TABLE jobs (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, dedupe TEXT,
 state TEXT NOT NULL CHECK(state IN ('Queued','Running','Completed','Failed')),
 created REAL NOT NULL, updated REAL NOT NULL, error TEXT
);
CREATE UNIQUE INDEX active_job ON jobs(dedupe) WHERE state IN ('Queued','Running');
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE play_history (
 id INTEGER PRIMARY KEY, media_id TEXT REFERENCES media(id) ON DELETE CASCADE,
 profile TEXT NOT NULL, requested REAL NOT NULL, success INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX history_time ON play_history(requested);
PRAGMA user_version=1;
COMMIT;
