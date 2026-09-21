import subprocess

import pytest
from mutagen.asf import ASF as Tags

from retrostream.streaming.asf import ASF
from retrostream.transcoder import PROFILES, command


@pytest.mark.parametrize("name", list(PROFILES))
def test_profiles_real_ffmpeg(name, ffmpeg, source, tmp_path):
    path = tmp_path / "output.asf"
    metadata = {
        "title": "Track",
        "artist": "Artist",
        "album": "Album",
        "album_artist": "Various",
        "year": "1999",
        "genre": "Test",
        "track_number": "3",
    }
    args = command(ffmpeg, source, path, PROFILES[name], metadata)
    subprocess.run(args, check=True, capture_output=True)
    media = ASF.read(path)
    assert media.duration_ms >= 5900
    tags = Tags(path)
    assert str(tags["Title"][0]) == "Track"
    assert str(tags["Author"][0]) == "Artist"
    assert str(tags["WM/AlbumTitle"][0]) == "Album"
    assert str(tags["WM/AlbumArtist"][0]) == "Various"
    assert str(tags["WM/Genre"][0]) == "Test"
    assert str(tags["WM/Year"][0]) == "1999"
    assert str(tags["WM/TrackNumber"][0]) == "3"
    decoded = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True,
    )
    assert decoded.returncode == 0, decoded.stderr.decode(errors="replace")
    if name.startswith("video-"):
        inspected = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True
        ).stderr.decode(errors="replace")
        expected = "wmv1" if name == "video-low" else "wmv2"
        assert f"Video: {expected}" in inspected, inspected
