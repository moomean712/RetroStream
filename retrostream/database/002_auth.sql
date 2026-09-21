BEGIN IMMEDIATE;
CREATE TABLE administrators (
 id INTEGER PRIMARY KEY CHECK(id=1),
 username TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL,
 created REAL NOT NULL
);
CREATE TABLE admin_sessions (
 token_hash TEXT PRIMARY KEY,
 created REAL NOT NULL,
 expires REAL NOT NULL
);
CREATE INDEX admin_sessions_expiry ON admin_sessions(expires);
PRAGMA user_version=2;
COMMIT;
