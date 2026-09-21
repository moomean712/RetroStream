"""File configuration with explicit environment overrides; no mutable UI state."""

import os
import re
import tomllib
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Config:
    bind: str = "127.0.0.1"
    hostname: str = "localhost"
    web_port: int = 8780
    streaming_port: int = 8781
    data_dir: str = "data"
    cache_dir: str = "data/cache"
    max_cache_bytes: int = 20 * 1024**3
    retention_days: int = 30
    cleanup_threshold: float = 0.90
    cleanup_target: float = 0.75
    cleanup_interval: int = 3600
    default_audio: str = "audio-standard"
    default_video: str = "video-standard"
    max_transcodes: int = 2
    max_streams: int = 16
    preparation_timeout: int = 1800
    subprocess_timeout: int = 7200
    max_import_entries: int = 1000
    ffmpeg: str = "ffmpeg"
    js_runtime: str = "deno"
    debug: bool = False

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", self.hostname):
            raise ValueError("hostname must be a LAN DNS name or IPv4 address, without port or scheme")
        if not (0 < self.cleanup_target < self.cleanup_threshold <= 1):
            raise ValueError("Require 0 < cleanup_target < cleanup_threshold <= 1")
        for key in ("web_port", "streaming_port"):
            if not 1 <= getattr(self, key) <= 65535:
                raise ValueError(f"Invalid {key}")
        for key in (
            "max_transcodes",
            "max_streams",
            "max_cache_bytes",
            "cleanup_interval",
            "preparation_timeout",
            "subprocess_timeout",
            "max_import_entries",
        ):
            if getattr(self, key) <= 0:
                raise ValueError(f"{key} must be positive")
        if self.retention_days < 0:
            raise ValueError("retention_days must be nonnegative")
        if self.default_audio not in ("audio-standard", "audio-high"):
            raise ValueError("Invalid default_audio")
        if self.default_video not in ("video-low", "video-standard", "video-high"):
            raise ValueError("Invalid default_video")
        if self.js_runtime not in ("deno", "node", "quickjs", "bun"):
            raise ValueError("Invalid JavaScript runtime")

    @property
    def web_url(self) -> str:
        return f"http://{self.hostname}:{self.web_port}"

    @property
    def stream_url(self) -> str:
        return f"http://{self.hostname}:{self.streaming_port}"

    def public(self) -> dict:
        return asdict(self)


def load(path: str | None = None) -> Config:
    path = path or os.environ.get("RETROSTREAM_CONFIG")
    values = {}
    if path:
        with Path(path).open("rb") as file:
            values = tomllib.load(file)
    defaults = Config()
    for field in fields(Config):
        raw = os.environ.get("RETROSTREAM_" + field.name.upper())
        if raw is not None:
            kind = type(getattr(defaults, field.name))
            values[field.name] = raw.lower() in ("true", "1", "yes") if kind is bool else kind(raw)
    return Config(**values)
