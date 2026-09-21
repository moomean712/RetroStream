import re
import time
import uuid

from .database import Database
from .metadata import clean, normalize


class Library:
    def __init__(self, db: Database):
        self.db = db

    def import_info(self, info: dict) -> str:
        external = info.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", external):
            raise ValueError("Invalid YouTube video ID")
        values = normalize(info)
        keys = list(values)
        with self.db.connect() as db:
            db.execute(
                f"INSERT INTO media(id,youtube_id,original_url,added,extracted,{','.join(keys)}) "
                f"VALUES(?,?,?,?,?,{','.join('?' for _ in keys)}) "
                "ON CONFLICT(youtube_id) DO UPDATE SET "
                + ",".join(f"{key}=excluded.{key}" for key in keys)
                + ",extracted=excluded.extracted,error=NULL",
                (
                    uuid.uuid4().hex,
                    external,
                    f"https://www.youtube.com/watch?v={external}",
                    time.time(),
                    time.time(),
                    *values.values(),
                ),
            )
            return db.execute("SELECT id FROM media WHERE youtube_id=?", (external,)).fetchone()[0]

    def media(self, media_id: str) -> dict:
        row = self.db.one("SELECT * FROM media WHERE id=?", (media_id,))
        if not row:
            raise KeyError("Media not found")
        return row

    def create_playlist(self, name: str) -> dict:
        name = clean(name.strip())
        if not name or len(name) > 200:
            raise ValueError("Playlist name must contain 1–200 characters")
        pid = uuid.uuid4().hex
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "playlist"
        slug += "-" + pid[:12]
        self.db.execute("INSERT INTO playlists VALUES(?,?,?,?)", (pid, slug, name, time.time()))
        return self.playlist(pid)

    def playlist(self, identifier: str) -> dict:
        row = self.db.one("SELECT * FROM playlists WHERE id=? OR slug=?", (identifier, identifier))
        if not row:
            raise KeyError("Playlist not found")
        row["items"] = self.db.all(
            "SELECT m.*,p.position FROM playlist_items p JOIN media m ON m.id=p.media_id "
            "WHERE p.playlist_id=? ORDER BY p.position,m.id",
            (row["id"],),
        )
        row["pins"] = [
            r["profile"]
            for r in self.db.all("SELECT profile FROM playlist_pins WHERE playlist_id=?", (row["id"],))
        ]
        return row

    def rename(self, pid: str, name: str):
        self.playlist(pid)
        name = clean(name.strip())
        if not name or len(name) > 200:
            raise ValueError("Playlist name must contain 1–200 characters")
        self.db.execute("UPDATE playlists SET name=? WHERE id=?", (name, pid))

    def add(self, pid: str, ids: list[str]):
        self.playlist(pid)
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            start = db.execute(
                "SELECT COALESCE(MAX(position),-1)+1 FROM playlist_items WHERE playlist_id=?", (pid,)
            ).fetchone()[0]
            for offset, mid in enumerate(ids):
                if not db.execute("SELECT 1 FROM media WHERE id=?", (mid,)).fetchone():
                    raise KeyError("Media not found")
                db.execute("INSERT OR IGNORE INTO playlist_items VALUES(?,?,?)", (pid, mid, start + offset))

    def reorder(self, pid: str, ids: list[str]):
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = [
                r[0] for r in db.execute("SELECT media_id FROM playlist_items WHERE playlist_id=?", (pid,))
            ]
            if len(set(ids)) != len(ids) or set(old) != set(ids):
                raise ValueError("Order must contain every playlist item exactly once")
            for position, mid in enumerate(ids):
                db.execute(
                    "UPDATE playlist_items SET position=? WHERE playlist_id=? AND media_id=?",
                    (position, pid, mid),
                )
