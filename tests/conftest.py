import re
import shutil
import subprocess

import imageio_ffmpeg
import pytest

from retrostream.config import Config
from retrostream.service import Service
from retrostream.transcoder import command, embed_artwork


def setup_admin(client, service):
    page = client.get("/setup")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    response = client.post(
        "/setup",
        data={
            "csrf": token,
            "code": service.auth.setup_code,
            "username": "admin",
            "password": "correct horse battery staple",
            "confirm_password": "correct horse battery staple",
            "return_to": "/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


@pytest.fixture(scope="session")
def ffmpeg():
    return imageio_ffmpeg.get_ffmpeg_exe()


@pytest.fixture(scope="session")
def source(tmp_path_factory, ffmpeg):
    path = tmp_path_factory.mktemp("fixture") / "source.mkv"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "6",
            "-c:v",
            "mpeg4",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
    )
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(path),
            "-frames:v",
            "1",
            str(path.with_name("cover.jpg")),
        ],
        check=True,
    )
    return path


class FakeYouTube:
    def entries(self, url):
        if "playlist?" in url:
            return [
                "https://www.youtube.com/watch?v=abcdefghijk",
                "https://www.youtube.com/watch?v=12345678901",
            ]
        return [url]

    def metadata(self, url):
        return {
            "id": url.split("v=")[-1],
            "title": "Video & <title>",
            "track": "Song & <title>",
            "artist": "Artist",
            "album": "Album",
            "album_artist": "Various",
            "genre": "Test",
            "release_year": 1999,
            "track_number": 3,
            "duration": 6,
        }


class FixtureTranscoder:
    def __init__(self, ffmpeg, source):
        self.ffmpeg, self.source = ffmpeg, source
        self.calls = 0

    def generate(self, media, profile, work, target):
        self.calls += 1
        subprocess.run(
            command(self.ffmpeg, self.source, target, profile, media), check=True, capture_output=True
        )
        artwork = work / "source.jpg"
        shutil.copyfile(self.source.with_name("cover.jpg"), artwork)
        embed_artwork(target, artwork)
        return artwork


@pytest.fixture
def service(tmp_path, ffmpeg, source):
    config = Config(
        data_dir=str(tmp_path / "data"),
        cache_dir=str(tmp_path / "cache"),
        ffmpeg=ffmpeg,
        max_cache_bytes=2_000_000,
        cleanup_interval=10000,
    )
    return Service(config, FakeYouTube(), FixtureTranscoder(ffmpeg, source))
