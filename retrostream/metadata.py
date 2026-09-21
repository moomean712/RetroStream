"""Conservative normalization: structured music tags first, never title guessing."""

import re


def clean(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = "; ".join(str(x) for x in value if x)
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]", "", str(value))[:4000] or None


def normalize(info: dict) -> dict:
    title = clean(info.get("title")) or info["id"]
    year = clean(info.get("release_year") or info.get("release_date"))
    if year and re.fullmatch(r"\d{8}", year):
        year = year[:4]
    return {
        "youtube_title": title,
        "title": clean(info.get("track")) or title,
        "artist": clean(
            info.get("artist") or info.get("artists") or info.get("uploader") or info.get("channel")
        ),
        "album": clean(info.get("album")),
        "album_artist": clean(info.get("album_artist")),
        "year": year,
        "genre": clean(info.get("genre") or info.get("genres")),
        "track_number": clean(info.get("track_number")),
        "uploader": clean(info.get("uploader") or info.get("channel")),
        "duration": max(0, float(info.get("duration") or 0)),
        "thumbnail_url": clean(info.get("thumbnail")),
    }
