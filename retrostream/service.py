"""Application orchestration; shared by the forms, JSON API, and streaming router."""

import importlib.metadata
import json
import logging
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path

from .auth import Auth
from .cache import Cache
from .database import Database
from .jobs import Jobs
from .library import Library
from .process import Processes
from .transcoder import PROFILES, Transcoder
from .youtube import YouTube, canonical_url

log = logging.getLogger(__name__)


class Service:
    def __init__(self, config, youtube=None, transcoder=None):
        self.config = config
        self.db = Database(Path(config.data_dir) / "retrostream.sqlite3")
        self.auth = Auth(self.db, config.web_url)
        self.library = Library(self.db)
        self.processes = Processes()
        self.youtube = youtube or YouTube(config, self.processes)
        self.cache = Cache(
            config, self.db, self.library, transcoder or Transcoder(config, self.youtube, self.processes)
        )
        self.jobs = Jobs(self.db, config.max_transcodes)
        self.jobs.handlers = {
            "import": self.import_urls,
            "transcode": self.transcode,
            "playlist-replace": self.playlist_replace,
            "cleanup": self.cache.cleanup,
            "refresh": self.refresh,
        }
        self.stop_event = threading.Event()
        self.scheduler = None

    def start(self):
        self.cache.reconcile()
        self.jobs.start()
        self.scheduler = threading.Thread(target=self._maintenance, name="maintenance", daemon=True)
        self.scheduler.start()
        log.info("application_startup")

    def close(self):
        self.stop_event.set()
        self.jobs.stop_event.set()
        self.processes.close()
        if self.scheduler:
            self.scheduler.join(timeout=5)
        self.jobs.close()

    def _maintenance(self):
        while not self.stop_event.is_set():
            try:
                self.jobs.submit("cleanup", {"mode": "automatic"}, "automatic-cleanup")
                self.prepare_pins()
                self.db.execute("DELETE FROM play_history WHERE requested<?", (time.time() - 90 * 86400,))
            except Exception:
                log.exception("maintenance_failure")
            self.stop_event.wait(self.config.cleanup_interval)

    def queue_import(self, urls: list[str], pid: str | None = None) -> str:
        if not urls or len(urls) > 100:
            raise ValueError("Supply 1–100 YouTube URLs per operation")
        urls = list(dict.fromkeys(canonical_url(url.strip())[1] for url in urls))
        if pid:
            self.library.playlist(pid)
        return self.jobs.submit("import", {"urls": urls, "pid": pid})

    def import_urls(self, urls: list[str], pid: str | None = None):
        failures = 0
        for url in urls:
            if self.stop_event.is_set():
                raise RuntimeError("Import interrupted by shutdown")
            try:
                entries = self.youtube.entries(url)
            except Exception:
                failures += 1
                continue
            for entry in entries:
                if self.stop_event.is_set():
                    raise RuntimeError("Import interrupted by shutdown")
                try:
                    info = self.youtube.metadata(entry)
                    mid = self.library.import_info(info)
                    if info.get("_artwork_bytes"):
                        self.cache.store_artwork(mid, info["_artwork_bytes"])
                    if pid and self.db.one("SELECT 1 FROM playlists WHERE id=?", (pid,)):
                        self.library.add(pid, [mid])
                    log.info("media_import", extra={"media": mid})
                except Exception as exc:
                    failures += 1
                    # Keep a placeholder for a valid unavailable video, including its playlist position.
                    _, canonical = canonical_url(entry)
                    external = canonical.split("v=")[-1]
                    existing = self.db.one("SELECT id FROM media WHERE youtube_id=?", (external,))
                    mid = (
                        existing["id"]
                        if existing
                        else self.library.import_info({"id": external, "title": external})
                    )
                    self.db.execute("UPDATE media SET error=? WHERE id=?", (str(exc)[:1000], mid))
                    if pid and self.db.one("SELECT 1 FROM playlists WHERE id=?", (pid,)):
                        self.library.add(pid, [mid])
        self.prepare_pins()
        if failures:
            raise RuntimeError(
                f"Import finished with {failures} unavailable inputs/items; successful items were kept"
            )

    def refresh(self, mid: str):
        media = self.library.media(mid)
        try:
            info = self.youtube.metadata(media["original_url"])
            self.library.import_info(info)
            if info.get("_artwork_bytes"):
                self.cache.store_artwork(mid, info["_artwork_bytes"])
        except Exception as exc:
            self.db.execute("UPDATE media SET error=? WHERE id=?", (str(exc)[:1000], mid))
            raise

    def queue_cache(self, mid: str, profile: str, direct_policy: bool | None = None) -> str:
        self.cache.register(mid, profile)
        policy = "preserve" if direct_policy is None else ("permanent" if direct_policy else "temporary")
        return self.jobs.submit(
            "transcode",
            {"mid": mid, "profile": profile, "direct_policy": direct_policy},
            f"cache:{mid}:{profile}:{policy}",
        )

    def transcode(self, mid: str, profile: str, direct_policy: bool | None = None):
        self.cache.ensure(mid, profile, direct_policy)
        self.cache.cleanup("automatic")

    def prepare_pins(self):
        protected = self.db.all(
            "SELECT media_id,profile FROM cache_entries WHERE pinned=1 UNION "
            "SELECT i.media_id,p.profile FROM playlist_pins p JOIN playlist_items i ON i.playlist_id=p.playlist_id"
        )
        requested = {}
        order = {profile: index for index, profile in enumerate(PROFILES)}
        for row in protected:
            key = row["media_id"], self.cache.kind(row["profile"])
            requested[key] = max(requested.get(key, row["profile"]), row["profile"], key=order.get)
        for (mid, kind), fallback in requested.items():
            profile = self.cache.active_profile(mid, kind, fallback)
            if not self.cache.path(mid, profile).exists():
                self.queue_cache(mid, profile)

    def playlist_cache(self, pid: str, profile: str, permanent: bool | None = None):
        if profile not in PROFILES:
            raise ValueError("Unknown profile")
        self.library.playlist(pid)
        jid = self.jobs.submit(
            "playlist-replace",
            {"pid": pid, "profile": profile, "permanent": permanent},
            f"playlist-cache:{pid}:{profile}:{permanent}",
        )
        return [jid]

    def playlist_replace(self, pid: str, profile: str, permanent: bool | None = None):
        playlist = self.library.playlist(pid)
        for item in playlist["items"]:
            self.cache.ensure(item["id"], profile)
        if permanent is not None:
            kind = self.cache.kind(profile)
            for candidate in PROFILES:
                if candidate.startswith(kind + "-"):
                    self.cache.playlist_pin(pid, candidate, permanent and candidate == profile)
        self.cache.cleanup("automatic")

    def retry(self, jid: str):
        job = self.db.one("SELECT * FROM jobs WHERE id=?", (jid,))
        if not job:
            raise KeyError("Job not found")
        if job["state"] != "Failed":
            raise ValueError("Only failed jobs can be retried")
        return self.jobs.submit(job["kind"], json.loads(job["payload"]), job["dedupe"])

    def status(self):
        cache_status = self.cache.stats()
        cache_status.pop("active_streams", None)
        return {
            **cache_status,
            "library_items": self.db.one("SELECT COUNT(*) n FROM media")["n"],
            "playlists": self.db.one("SELECT COUNT(*) n FROM playlists")["n"],
            "python": sys.version.split()[0],
            "sqlite": sqlite3.sqlite_version,
            "yt_dlp": importlib.metadata.version("yt-dlp"),
            "ffmpeg": shutil.which(self.config.ffmpeg) or "Not found",
            "js_runtime": shutil.which(self.config.js_runtime) or "Not found",
            "failures": self.db.all(
                "SELECT id,kind,error,updated FROM jobs WHERE state='Failed' ORDER BY updated DESC LIMIT 10"
            ),
        }
