import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mutagen.asf import ASF, ASFByteArrayAttribute

from .process import Processes


@dataclass(frozen=True)
class Profile:
    name: str
    audio_bitrate: str
    width: int = 0
    height: int = 0
    video_bitrate: str = ""
    video_codec: str = "wmv2"
    cache_version: int = 1

    @property
    def audio(self):
        return self.width == 0

    @property
    def extension(self):
        return ".wma" if self.audio else ".wmv"


PROFILES = {
    p.name: p
    for p in (
        Profile("audio-standard", "128k"),
        Profile("audio-high", "192k"),
        Profile("video-low", "128k", 320, 240, "450k", "wmv1", 2),
        Profile("video-standard", "128k", 640, 360, "900k"),
        Profile("video-high", "192k", 854, 480, "1500k"),
    )
}


def embed_artwork(target: Path, artwork: Path):
    image = artwork.read_bytes()
    picture = (
        b"\x03"
        + struct.pack("<I", len(image))
        + "image/jpeg".encode("utf-16-le")
        + b"\x00\x00"
        + "Cover".encode("utf-16-le")
        + b"\x00\x00"
        + image
    )
    tags = ASF(target)
    tags["WM/Picture"] = [ASFByteArrayAttribute(picture)]
    tags.save()


def command(ffmpeg: str, source: Path, target: Path, profile: Profile, media: dict) -> list[str]:
    args = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-protocol_whitelist",
        "file,pipe",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-c:a",
        "wmav2",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-b:a",
        profile.audio_bitrate,
    ]
    if profile.audio:
        args += ["-vn"]
    else:
        args += [
            "-map",
            "0:v:0",
            "-c:v",
            profile.video_codec,
            "-pix_fmt",
            "yuv420p",
            "-r",
            "25",
            "-g",
            "50",
            "-b:v",
            profile.video_bitrate,
            "-vf",
            f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
            f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2,setsar=1",
        ]
    args += ["-map_metadata", "-1"]
    for key, tag in (
        ("title", "title"),
        ("artist", "artist"),
        ("album", "album"),
        ("album_artist", "album_artist"),
        ("genre", "genre"),
        ("year", "WM/Year"),
        ("track_number", "track"),
    ):
        if media.get(key):
            args += ["-metadata", f"{tag}={media[key]}"]
    return args + ["-f", "asf", str(target)]


class Transcoder:
    def __init__(self, config, youtube, processes=None):
        self.config, self.youtube = config, youtube
        self.processes = processes or Processes()

    def generate(self, media: dict, profile: Profile, work: Path, target: Path):
        source = self.youtube.download(media["original_url"], work, profile.audio)
        artwork = Path(media["_artwork_path"]) if media.get("_artwork_path") else None
        try:
            result = self.processes.run(
                command(self.config.ffmpeg, source, target, profile, media),
                timeout=self.config.subprocess_timeout,
            )
        except FileNotFoundError:
            raise RuntimeError("FFmpeg executable was not found; check Settings") from None
        except subprocess.TimeoutExpired:
            raise RuntimeError("Transcoding exceeded the configured timeout") from None
        if result.returncode or not target.exists() or target.stat().st_size < 100:
            raise RuntimeError(
                "FFmpeg could not create the requested representation; check source audio/video"
            )
        if artwork:
            embed_artwork(target, artwork)
        return artwork
