import pytest

from retrostream.config import Config
from retrostream.database import Database
from retrostream.library import Library
from retrostream.metadata import normalize
from retrostream.youtube import canonical_url


@pytest.fixture
def library(tmp_path):
    return Library(Database(tmp_path / "db.sqlite"))


def test_library_persistence_and_duplicates(library):
    mid = library.import_info({"id": "abcdefghijk", "title": "Video", "track": "Song", "artist": "Artist"})
    assert library.import_info({"id": "abcdefghijk", "title": "Updated"}) == mid
    assert Library(Database(library.db.path)).media(mid)["title"] == "Updated"
    assert len(library.db.all("SELECT * FROM media")) == 1
    assert library.db.one("PRAGMA user_version")["user_version"] == 4


def test_playlist_stable_slug_order_remove(library):
    a = library.import_info({"id": "abcdefghijk", "title": "A"})
    b = library.import_info({"id": "12345678901", "title": "B"})
    p = library.create_playlist("90s Mix")
    library.add(p["id"], [a, b, a])
    library.rename(p["id"], "New name")
    library.reorder(p["id"], [b, a])
    assert library.playlist(p["slug"])["name"] == "New name"
    assert [r["id"] for r in library.playlist(p["slug"])["items"]] == [b, a]
    with pytest.raises(ValueError):
        library.reorder(p["id"], [a, a])
    library.db.execute("DELETE FROM playlist_items WHERE playlist_id=? AND media_id=?", (p["id"], a))
    assert len(library.playlist(p["id"])["items"]) == 1


def test_metadata():
    row = normalize(
        {
            "id": "abcdefghijk",
            "title": "Arbitrary - title",
            "artists": ["A", "B"],
            "track": "Track",
            "album": "Album",
            "release_year": 1999,
            "track_number": 3,
        }
    )
    assert (row["title"], row["artist"], row["year"], row["track_number"]) == ("Track", "A; B", "1999", "3")
    assert normalize({"id": "abcdefghijk", "title": "A - B", "uploader": "Channel"})["title"] == "A - B"


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://youtube.com.evil/watch?v=abcdefghijk",
        "https://user@youtube.com/watch?v=abcdefghijk",
        "https://youtube.com:443/watch?v=abcdefghijk",
        "https://127.0.0.1/",
        "https://youtu.be/../../etc",
        "https://youtu.be/a;echo$()",
        "https://youtu.be/abcdefghijk\n",
        "--exec=evil",
        "https://youtube.com/redirect?q=http://localhost",
    ],
)
def test_reject_urls(url):
    with pytest.raises(ValueError):
        canonical_url(url)


def test_canonical_urls():
    assert canonical_url("https://youtu.be/abcdefghijk?t=30")[1].endswith("v=abcdefghijk")
    assert canonical_url("https://youtube.com/watch?v=abcdefghijk&list=PL1234567890")[0] == "video"
    assert canonical_url("https://youtube.com/playlist?list=PL1234567890")[0] == "playlist"
    with pytest.raises(ValueError):
        Config(cleanup_target=0.99)
