"""Representation cache with atomic publication, reference pins and stream leases."""

import logging
import re
import shutil
import tempfile
import threading
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from .streaming.asf import ASF
from .transcoder import PROFILES

log = logging.getLogger(__name__)


class Cache:
    def __init__(self, config, db, library, transcoder):
        self.config, self.db, self.library, self.transcoder = config, db, library, transcoder
        self.root = Path(config.cache_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.work = self.root / ".work"
        self.work.mkdir(exist_ok=True)
        self.artwork = self.root / "artwork"
        self.artwork.mkdir(exist_ok=True)
        self.condition = threading.Condition(threading.RLock())
        self.generating = set()
        self.users = Counter()

    def path(self, mid: str, profile: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", mid) or profile not in PROFILES:
            raise ValueError("Invalid media ID or profile")
        path = self.root / mid / (profile + PROFILES[profile].extension)
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("Unsafe cache path")
        return path

    def artwork_path(self, mid: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", mid):
            raise ValueError("Invalid media ID")
        return self.artwork / (mid + ".jpg")

    def store_artwork(self, mid: str, data: bytes):
        if len(data) > 10 * 1024 * 1024 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
            raise ValueError("Invalid album artwork")
        path = self.artwork_path(mid)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    def register(self, mid: str, profile: str):
        self.path(mid, profile)
        self.library.media(mid)
        self.db.execute(
            "INSERT OR IGNORE INTO cache_entries(media_id,profile,last_accessed) VALUES(?,?,?)",
            (mid, profile, time.time()),
        )

    @staticmethod
    def kind(profile: str) -> str:
        return profile.split("-", 1)[0]

    def active_profile(self, mid: str, kind: str, fallback: str | None = None) -> str | None:
        if kind not in ("audio", "video"):
            raise ValueError("Invalid cache kind")
        row = self.db.one("SELECT profile FROM cache_preferences WHERE media_id=? AND kind=?", (mid, kind))
        profile = row["profile"] if row else fallback
        return profile if profile in PROFILES and profile.startswith(kind + "-") else fallback

    def _kind_protected(self, mid: str, kind: str) -> bool:
        pattern = kind + "-%"
        return bool(
            self.db.one(
                "SELECT 1 FROM cache_entries WHERE media_id=? AND profile LIKE ? AND pinned=1 "
                "UNION ALL SELECT 1 FROM playlist_pins p JOIN playlist_items i "
                "ON i.playlist_id=p.playlist_id WHERE i.media_id=? AND p.profile LIKE ? LIMIT 1",
                (mid, pattern, mid, pattern),
            )
        )

    def pinned(self, mid: str, profile: str) -> bool:
        kind = self.kind(profile)
        active = self.active_profile(mid, kind)
        if active and active != profile:
            return False
        return self._kind_protected(mid, kind)

    def entries(self, mid: str | None = None) -> list[dict]:
        rows = self.db.all(
            "SELECT * FROM cache_entries" + (" WHERE media_id=?" if mid else ""), (mid,) if mid else ()
        )
        for row in rows:
            row["is_pinned"] = self.pinned(row["media_id"], row["profile"])
            if row["state"] == "CACHED" and row["is_pinned"]:
                row["state"] = "PINNED"
        return rows

    def reconcile(self):
        # Only service-generated directories are removed; never follow directory symlinks.
        for child in self.work.iterdir():
            if child.is_dir() and not child.is_symlink() and child.name.startswith("rs-"):
                shutil.rmtree(child)
        for media in self.db.all("SELECT id FROM media"):
            for profile in PROFILES:
                mid = media["id"]
                self.register(mid, profile)
                path = self.path(mid, profile)
                row = self.db.one(
                    "SELECT profile_version FROM cache_entries WHERE media_id=? AND profile=?",
                    (mid, profile),
                )
                if row["profile_version"] != PROFILES[profile].cache_version:
                    path.unlink(missing_ok=True)
                    self.db.execute(
                        "UPDATE cache_entries SET state='UNCACHED',size=0,error=NULL,profile_version=? "
                        "WHERE media_id=? AND profile=?",
                        (PROFILES[profile].cache_version, mid, profile),
                    )
                size = path.stat().st_size if path.is_file() else 0
                state = "CACHED" if size else "UNCACHED"
                error = None
                if path.exists():
                    try:
                        ASF.read(path)
                    except (ValueError, OSError):
                        path.unlink(missing_ok=True)
                        state, size, error = (
                            "FAILED",
                            0,
                            "Incomplete or invalid cache file removed during recovery",
                        )
                self.db.execute(
                    "UPDATE cache_entries SET state=?,size=?,error=? WHERE media_id=? AND profile=?",
                    (state, size, error, mid, profile),
                )

            # Older installations may contain several representations of one media type.
            # Validate everything first, then retain one deterministically and retire the rest.
            for kind in ("audio", "video"):
                cached = self.db.all(
                    "SELECT * FROM cache_entries WHERE media_id=? AND profile LIKE ? "
                    "AND state='CACHED' ORDER BY last_accessed DESC,profile",
                    (mid, kind + "-%"),
                )
                if not cached:
                    self.db.execute("DELETE FROM cache_preferences WHERE media_id=? AND kind=?", (mid, kind))
                    continue
                preferred = self.active_profile(mid, kind)
                profiles = {row["profile"] for row in cached}
                if preferred not in profiles:
                    protected = [
                        row
                        for row in cached
                        if row["pinned"]
                        or self.db.one(
                            "SELECT 1 FROM playlist_pins p JOIN playlist_items i "
                            "ON i.playlist_id=p.playlist_id WHERE i.media_id=? AND p.profile=? LIMIT 1",
                            (mid, row["profile"]),
                        )
                    ]
                    preferred = (protected or cached)[0]["profile"]
                self._activate(mid, preferred)

    def ensure(self, mid: str, profile: str, direct_policy: bool | None = None) -> Path:
        key = (mid, profile)
        generation_key = (mid, self.kind(profile))
        path = self.path(mid, profile)
        with self.condition:
            self.register(mid, profile)
            while generation_key in self.generating:
                self.condition.wait()
            row = self.db.one("SELECT profile_version FROM cache_entries WHERE media_id=? AND profile=?", key)
            if row["profile_version"] != PROFILES[profile].cache_version:
                path.unlink(missing_ok=True)
                self.db.execute(
                    "UPDATE cache_entries SET state='UNCACHED',size=0,error=NULL,profile_version=? "
                    "WHERE media_id=? AND profile=?",
                    (PROFILES[profile].cache_version, *key),
                )
            if path.is_file():
                self._activate(mid, profile, direct_policy)
                log.info("cache_hit", extra={"media": mid, "profile": profile})
                return path
            self.generating.add(generation_key)
            self.db.execute(
                "UPDATE cache_entries SET state='CACHING',error=NULL WHERE media_id=? AND profile=?", key
            )
        log.info("transcode_start", extra={"media": mid, "profile": profile})
        try:
            with tempfile.TemporaryDirectory(prefix="rs-", dir=self.work) as directory:
                work = Path(directory)
                target = work / "output.asf"
                media = self.library.media(mid)
                saved_artwork = self.artwork_path(mid)
                if saved_artwork.is_file():
                    media["_artwork_path"] = str(saved_artwork)
                artwork = self.transcoder.generate(media, PROFILES[profile], work, target)
                ASF.read(target)  # Reject incomplete or unsupported output before publishing it.
                with self.condition:
                    path.parent.mkdir(exist_ok=True)
                    target.replace(path)
                    if (
                        artwork
                        and artwork.is_file()
                        and artwork.resolve() != self.artwork_path(mid).resolve()
                    ):
                        shutil.copyfile(artwork, self.artwork_path(mid))
                    self._activate(mid, profile, direct_policy)
            log.info("transcode_complete", extra={"media": mid, "profile": profile})
            return path
        except Exception as exc:
            self.db.execute(
                "UPDATE cache_entries SET state='FAILED',error=? WHERE media_id=? AND profile=?",
                (str(exc)[:1000], *key),
            )
            log.warning("transcode_failed", extra={"media": mid, "profile": profile})
            raise
        finally:
            with self.condition:
                self.generating.discard(generation_key)
                self.condition.notify_all()

    def _activate(self, mid: str, profile: str, direct_policy: bool | None = None):
        """Commit a prepared profile as active, then retire superseded files."""
        kind = self.kind(profile)
        path = self.path(mid, profile)
        if not path.is_file():
            raise ValueError("Cannot activate a missing cache representation")
        preserved_direct = bool(
            self.db.one(
                "SELECT 1 FROM cache_entries WHERE media_id=? AND profile LIKE ? AND pinned=1 LIMIT 1",
                (mid, kind + "-%"),
            )
        )
        direct = preserved_direct if direct_policy is None else direct_policy
        now = time.time()
        with self.db.connect() as db:
            db.execute(
                "INSERT INTO cache_preferences(media_id,kind,profile,updated) VALUES(?,?,?,?) "
                "ON CONFLICT(media_id,kind) DO UPDATE SET profile=excluded.profile,updated=excluded.updated",
                (mid, kind, profile, now),
            )
            db.execute(
                "UPDATE cache_entries SET pinned=0 WHERE media_id=? AND profile LIKE ?",
                (mid, kind + "-%"),
            )
            db.execute(
                "UPDATE cache_entries SET state='CACHED',size=?,last_accessed=?,error=NULL,pinned=?,"
                "profile_version=? "
                "WHERE media_id=? AND profile=?",
                (
                    path.stat().st_size,
                    now,
                    int(direct),
                    PROFILES[profile].cache_version,
                    mid,
                    profile,
                ),
            )
        self._retire_superseded(mid, kind, profile)

    def _retire_superseded(self, mid: str, kind: str, keep: str):
        for row in self.db.all(
            "SELECT profile FROM cache_entries WHERE media_id=? AND profile LIKE ? AND profile<>?",
            (mid, kind + "-%", keep),
        ):
            key = (mid, row["profile"])
            if self.users[key]:
                continue
            self.path(*key).unlink(missing_ok=True)
            self.db.execute(
                "UPDATE cache_entries SET state='UNCACHED',size=0,pinned=0,error=NULL "
                "WHERE media_id=? AND profile=?",
                key,
            )

    @contextmanager
    def lease(self, mid: str, profile: str):
        key = (mid, profile)
        with self.condition:
            if sum(self.users.values()) >= self.config.max_streams:
                raise RuntimeError("Maximum simultaneous streams reached")
            self.users[key] += 1
        try:
            yield
        finally:
            with self.condition:
                self.users[key] -= 1
                if not self.users[key]:
                    del self.users[key]
                    active = self.active_profile(mid, self.kind(profile))
                    if active and active != profile:
                        self._retire_superseded(mid, self.kind(profile), active)

    def pin(self, mid: str, profile: str, enabled: bool):
        with self.condition:
            self.register(mid, profile)
            self.db.execute(
                "UPDATE cache_entries SET pinned=? WHERE media_id=? AND profile=?",
                (int(enabled), mid, profile),
            )

    def delete_media(self, mid: str):
        """Delete one library item and every file and dependent record it owns."""
        self.library.media(mid)
        keys = [(mid, profile) for profile in PROFILES]
        with self.condition:
            if any(
                (mid, self.kind(profile)) in self.generating or self.users[(mid, profile)]
                for profile in PROFILES
            ):
                raise ValueError("Stop active preparation or playback before deleting this track")
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute(
                    "SELECT 1 FROM jobs WHERE state='Running' AND payload LIKE ?", (f"%{mid}%",)
                ).fetchone():
                    raise ValueError("Wait for the active task to finish before deleting this track")
                db.execute("DELETE FROM jobs WHERE state='Queued' AND payload LIKE ?", (f"%{mid}%",))
                for key in keys:
                    self.path(*key).unlink(missing_ok=True)
                self.artwork_path(mid).unlink(missing_ok=True)
                directory = self.root / mid
                if directory.is_dir() and not directory.is_symlink():
                    try:
                        directory.rmdir()
                    except OSError:
                        pass
                db.execute("DELETE FROM media WHERE id=?", (mid,))
        log.info("library_media_deleted", extra={"media": mid})

    def playlist_pin(self, pid: str, profile: str, enabled: bool):
        if profile not in PROFILES:
            raise ValueError("Invalid profile")
        self.library.playlist(pid)
        with self.condition:
            if enabled:
                self.db.execute("INSERT OR IGNORE INTO playlist_pins VALUES(?,?)", (pid, profile))
            else:
                self.db.execute("DELETE FROM playlist_pins WHERE playlist_id=? AND profile=?", (pid, profile))

    def cleanup(
        self,
        mode: str = "unused",
        kind: str = "all",
        media_ids: list[str] | None = None,
        include_permanent: bool = False,
    ):
        if mode not in ("unused", "clear", "automatic") or kind not in ("all", "audio", "video"):
            raise ValueError("Invalid cleanup mode")
        removed = 0
        with self.condition:
            if include_permanent and media_ids is None:
                if kind == "all":
                    self.db.execute("UPDATE cache_entries SET pinned=0")
                    self.db.execute("DELETE FROM playlist_pins")
                else:
                    self.db.execute("UPDATE cache_entries SET pinned=0 WHERE profile LIKE ?", (kind + "-%",))
                    self.db.execute("DELETE FROM playlist_pins WHERE profile LIKE ?", (kind + "-%",))
            rows = self.db.all("SELECT * FROM cache_entries ORDER BY last_accessed,media_id,profile")
            total = sum(row["size"] for row in rows)
            pressure = total >= self.config.max_cache_bytes * self.config.cleanup_threshold
            target = self.config.max_cache_bytes * self.config.cleanup_target
            cutoff = time.time() - self.config.retention_days * 86400
            for row in rows:
                key = row["media_id"], row["profile"]
                if (
                    row["state"] != "CACHED"
                    or (key[0], self.kind(key[1])) in self.generating
                    or self.users[key]
                    or (self.pinned(*key) and not include_permanent)
                ):
                    continue
                if media_ids is not None and key[0] not in media_ids:
                    continue
                if kind != "all" and not key[1].startswith(kind + "-"):
                    continue
                expired = row["last_accessed"] < cutoff
                if mode != "clear" and not expired and not (pressure and total > target):
                    continue
                self.path(*key).unlink(missing_ok=True)
                self.db.execute(
                    "UPDATE cache_entries SET state='UNCACHED',size=0,error=NULL "
                    "WHERE media_id=? AND profile=?",
                    key,
                )
                if self.active_profile(key[0], self.kind(key[1])) == key[1]:
                    self.db.execute(
                        "DELETE FROM cache_preferences WHERE media_id=? AND kind=?",
                        (key[0], self.kind(key[1])),
                    )
                total -= row["size"]
                removed += row["size"]
        log.info(
            "cache_cleanup",
            extra={"removed_bytes": removed, "mode": mode, "include_permanent": include_permanent},
        )
        return removed

    def stats(self) -> dict:
        rows = self.entries()
        return {
            "total": sum(r["size"] for r in rows),
            "audio": sum(r["size"] for r in rows if r["profile"].startswith("audio")),
            "video": sum(r["size"] for r in rows if r["profile"].startswith("video")),
            "pinned": sum(r["size"] for r in rows if r["is_pinned"]),
            "cached": sum(r["state"] in ("CACHED", "PINNED") for r in rows),
            "uncached_items": self.db.one(
                "SELECT COUNT(*) n FROM media m WHERE NOT EXISTS "
                "(SELECT 1 FROM cache_entries c WHERE c.media_id=m.id AND c.state='CACHED')"
            )["n"],
            "maximum": self.config.max_cache_bytes,
            "active_streams": sum(self.users.values()),
            "active_transcodes": len(self.generating),
            "free_disk": shutil.disk_usage(self.root).free,
        }
