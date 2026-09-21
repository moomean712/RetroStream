BEGIN IMMEDIATE;
CREATE TABLE cache_preferences (
 media_id TEXT REFERENCES media(id) ON DELETE CASCADE,
 kind TEXT NOT NULL CHECK(kind IN ('audio','video')),
 profile TEXT NOT NULL, updated REAL NOT NULL,
 PRIMARY KEY(media_id, kind)
);
PRAGMA user_version=3;
COMMIT;
