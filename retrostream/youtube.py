"""Only canonical YouTube inputs reach yt-dlp; never use a shell."""

import json
import logging
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .process import Processes

log = logging.getLogger(__name__)
VIDEO = re.compile(r"[A-Za-z0-9_-]{11}\Z")
PLAYLIST = re.compile(r"[A-Za-z0-9_-]{10,100}\Z")


def canonical_url(value: str) -> tuple[str, str]:
    if len(value) > 2048 or any(ord(c) < 33 for c in value) or "\\" in value:
        raise ValueError("Invalid YouTube URL")
    try:
        url = urlsplit(value)
        if url.scheme not in ("http", "https") or url.username or url.password or url.port:
            raise ValueError("Use a YouTube HTTP(S) URL without credentials or a port")
        host = (url.hostname or "").lower()
        if host not in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"):
            raise ValueError("Only YouTube URLs are supported")
        query = parse_qs(url.query)
        if host == "youtu.be":
            video = url.path.removeprefix("/")
        elif url.path == "/watch":
            video = query.get("v", [""])[0]
        elif re.fullmatch(r"/(shorts|live|embed)/[^/]+", url.path):
            video = url.path.split("/")[-1]
        elif url.path == "/playlist":
            playlist = query.get("list", [""])[0]
            if not PLAYLIST.fullmatch(playlist):
                raise ValueError("Invalid playlist ID")
            return "playlist", "https://www.youtube.com/playlist?list=" + playlist
        else:
            raise ValueError("Use a video or playlist URL")
        if not VIDEO.fullmatch(video):
            raise ValueError("Invalid video ID")
        return "video", "https://www.youtube.com/watch?v=" + video
    except (TypeError, IndexError) as exc:
        raise ValueError("Invalid YouTube URL") from exc


class YouTube:
    def __init__(self, config, processes=None):
        self.config = config
        self.processes = processes or Processes()

    def run(self, options: list[str], url: str) -> str:
        _, url = canonical_url(url)
        args = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--no-warnings",
            "--no-progress",
            "--socket-timeout",
            "30",
            "--retries",
            "2",
            "--js-runtimes",
            self.config.js_runtime,
            *options,
            "--",
            url,
        ]
        try:
            result = self.processes.run(args, text=True, timeout=self.config.subprocess_timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError("YouTube operation timed out; retry from System Status") from None
        if result.returncode:
            # yt-dlp output can contain signed URLs/cookies; do not retain it in logs or jobs.
            error = result.stderr.lower()
            for marker, reason in (
                ("private video", "This video is private"),
                ("not available in your country", "This video is region restricted"),
                ("sign in", "YouTube requires sign-in; authenticated media is unsupported"),
                ("video unavailable", "This video is unavailable or deleted"),
                ("no space left", "The cache disk is full"),
                (
                    "requested format is not available",
                    "No usable source format; update yt-dlp and check the JS runtime",
                ),
            ):
                if marker in error:
                    raise RuntimeError(reason)
            raise RuntimeError(
                "YouTube extraction/download failed: item may be unavailable, restricted, "
                "or yt-dlp/runtime may need updating"
            )
        return result.stdout

    def entries(self, url: str) -> list[str]:
        kind, url = canonical_url(url)
        if kind == "video":
            return [url]
        raw = self.run(
            [
                "--flat-playlist",
                "--dump-single-json",
                "--skip-download",
                "--playlist-end",
                str(self.config.max_import_entries),
            ],
            url,
        )
        info = json.loads(raw)
        return [
            "https://www.youtube.com/watch?v=" + entry["id"]
            for entry in info.get("entries", [])
            if entry and VIDEO.fullmatch(entry.get("id", ""))
        ]

    def metadata(self, url: str) -> dict:
        log.info("metadata_extraction_start")
        with tempfile.TemporaryDirectory(prefix="retrostream-art-") as directory:
            info = json.loads(
                self.run(
                    [
                        "--no-playlist",
                        "--dump-single-json",
                        "--skip-download",
                        "--write-thumbnail",
                        "--convert-thumbnails",
                        "jpg",
                        "--ffmpeg-location",
                        self.config.ffmpeg,
                        "-o",
                        str(Path(directory) / "cover.%(ext)s"),
                    ],
                    url,
                )
            )
            artwork = Path(directory) / "cover.jpg"
            if artwork.is_file() and artwork.stat().st_size <= 10 * 1024 * 1024:
                info["_artwork_bytes"] = artwork.read_bytes()
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            raise ValueError("Live and upcoming broadcasts are not supported; use completed VOD media")
        if info.get("has_drm"):
            raise ValueError("Protected media is not supported")
        log.info("metadata_extraction_complete")
        return info

    def download(self, url: str, directory: Path, audio: bool) -> Path:
        self.run(
            [
                "--no-playlist",
                "--no-continue",
                "--no-part",
                "--match-filter",
                "!is_live & !is_upcoming & !has_drm",
                "--max-filesize",
                str(self.config.max_cache_bytes),
                "--ffmpeg-location",
                self.config.ffmpeg,
                "-f",
                "bestaudio/best" if audio else "bestvideo[height<=480]+bestaudio/best[height<=480]",
                "-o",
                str(directory / "source.%(ext)s"),
            ],
            url,
        )
        candidates = [p for p in directory.glob("source.*") if p.is_file()]
        if len(candidates) != 1:
            raise RuntimeError("Download did not produce one complete source file")
        return candidates[0]
