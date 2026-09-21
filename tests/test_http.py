import re
import struct
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient
from mutagen.asf import ASF as Tags

from retrostream.app import create_app
from retrostream.streaming.asf import ASF
from retrostream.streaming.http import byte_range
from retrostream.streaming.wmsp import frame, pragmas
from tests.conftest import setup_admin


@pytest.fixture
def client(service):
    with TestClient(create_app(service=service), base_url="http://localhost") as client:
        setup_admin(client, service)
        token = client.get("/api/csrf").json()["csrf_token"]
        client.headers["X-CSRF-Token"] = token
        yield client


def test_pages_and_csrf(service, client):
    playlist = client.post("/api/playlists", json={"name": "<script> & mix"}).json()
    for path in (
        "/",
        "/library",
        "/playlists",
        "/add",
        "/storage",
        "/settings",
        "/status",
        "/playlists/" + playlist["slug"],
    ):
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert 'name="viewport"' in response.text
        assert 'href="/static/favicon.ico"' in response.text
    assert client.get("/static/favicon.ico").headers["content-type"].startswith("image/")
    assert "&lt;script&gt;" in client.get("/playlists").text
    assert client.get("/actions/clear").status_code == 405
    assert client.post("/api/cache/clear", json={"kind": "all"}).status_code == 400
    token = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/playlists", json={"name": "blocked"}).status_code == 403
    response = client.post(
        "/actions/create", data={"csrf": token, "name": "Via forms"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400
    assert client.post("/api/playlists", content=b"x" * 140000).status_code == 413


def test_health_is_public_and_minimal(service):
    with TestClient(create_app(service=service), base_url="http://localhost") as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_playlist_api_asx(service, client):
    service.import_urls(["https://www.youtube.com/playlist?list=PL1234567890"])
    ids = [r["id"] for r in client.get("/api/media").json()]
    playlist = client.post("/api/playlists", json={"name": "My Mix"}).json()
    pid = playlist["id"]
    assert client.post(f"/api/playlists/{pid}/items", json={"media_ids": ids}).status_code == 200
    assert client.patch(f"/api/playlists/{pid}", json={"name": "Renamed"}).status_code == 200
    client.post(f"/api/playlists/{pid}/reorder", json={"media_ids": ids[::-1]})
    assert client.get(f"/playlists/{playlist['slug']}").status_code == 200
    for mode in ("audio", "video"):
        response = client.get(f"/playlists/{playlist['slug']}/{mode}.asx")
        assert response.status_code == 200
        assert response.content.startswith(b"<ASX")
        root = ElementTree.fromstring(response.content)
        assert root.find("PARAM[@NAME='Encoding']").attrib["VALUE"] == "utf-8"
        assert root.find("PARAM[@NAME='AllowShuffle']").attrib["VALUE"] == "Yes"
        assert root.findtext("TITLE") == "Renamed"
        entries = root.findall("ENTRY")
        assert len(entries) == 2
        assert entries[0].findtext("TITLE") == "Song & <title>"
        assert entries[0].findtext("AUTHOR") == "Artist"
        assert entries[0].find("REF").attrib["HREF"] == f"{service.config.stream_url}/media/{ids[1]}/{mode}"
        downloaded = client.get(f"/playlists/{playlist['slug']}/{mode}.asx?download=1")
        assert downloaded.headers["content-disposition"] == (
            f'attachment; filename="Renamed - {mode.title()}.asx"'
        )
        wpl = client.get(f"/playlists/{playlist['slug']}/{mode}.wpl")
        assert wpl.status_code == 200
        assert wpl.headers["content-type"].startswith("application/vnd.ms-wpl")
        assert wpl.content.startswith(b'<?wpl version="1.0"?>')
        assert wpl.content.count(b"<media ") == 2
        assert f"/media/{ids[1]}/{mode}/".encode() in wpl.content
        assert (b".wma" if mode == "audio" else b".wmv") in wpl.content
    service.db.execute("UPDATE media SET error='Unavailable' WHERE id=?", (ids[0],))
    root = ElementTree.fromstring(client.get(f"/playlists/{playlist['slug']}/audio.asx").content)
    assert len(root.findall("ENTRY")) == 1
    assert client.delete(f"/api/playlists/{pid}").status_code == 400
    assert client.delete(f"/api/playlists/{pid}?confirm=true").status_code == 200
    assert len(client.get("/api/media").json()) == 2


def test_actions_return_to_origin_and_profiles_are_separate(service, client):
    service.import_urls(["https://www.youtube.com/watch?v=abcdefghijk"])
    mid = service.db.one("SELECT id FROM media")["id"]
    playlist = client.post("/api/playlists", json={"name": "retro"}).json()
    origin = f"/library?q=Song&page=1#media-{mid}"
    response = client.post(
        "/actions/add-items",
        data={"pid": playlist["id"], "media_ids": mid, "return_to": origin},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/library?q=Song&page=1&notice=")
    assert response.headers["location"].endswith(f"#media-{mid}")
    response = client.post(
        "/actions/pin",
        data={"mid": mid, "profile": "audio-high", "enabled": "yes", "return_to": origin},
        follow_redirects=False,
    )
    assert response.headers["location"].startswith("/library?q=Song&page=1&notice=")
    queued = service.db.one("SELECT payload FROM jobs WHERE kind='transcode'")
    assert '"profile": "audio-high"' in queued["payload"]
    assert '"direct_policy": true' in queued["payload"]
    assert not service.db.one(
        "SELECT 1 FROM cache_entries WHERE media_id=? AND profile='video-standard'", (mid,)
    )
    unsafe = client.post(
        "/actions/refresh",
        data={"mid": mid, "return_to": "https://evil.example/"},
        follow_redirects=False,
    )
    assert unsafe.headers["location"].startswith("/?notice=")
    page = client.get(f"/library/{mid}").text
    audio = page[page.index("audio-cache") : page.index("video-cache")]
    video = page[page.index("video-cache") : page.index("danger-zone")]
    assert "audio-standard" in audio and "audio-high" in audio and "video-" not in audio
    assert all(profile in video for profile in ("video-low", "video-standard", "video-high"))
    assert "audio-" not in video


def test_library_delete_removes_every_dependent_record_and_cached_file(service, client):
    service.import_urls(["https://www.youtube.com/watch?v=abcdefghijk"])
    mid = service.db.one("SELECT id FROM media")["id"]
    playlist = service.library.create_playlist("Delete test")
    service.library.add(playlist["id"], [mid])
    audio = service.cache.ensure(mid, "audio-standard")
    video = service.cache.ensure(mid, "video-standard")
    artwork = service.cache.artwork_path(mid)
    assert artwork.exists()
    service.cache.pin(mid, "audio-standard", True)
    service.db.execute(
        "INSERT INTO play_history(media_id,profile,requested,success) VALUES(?,?,?,1)",
        (mid, "audio-standard", 1),
    )

    response = client.post(
        "/actions/delete-media",
        data={"mid": mid, "confirm": "yes", "return_to": f"/library/{mid}"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/library?notice=")
    assert not audio.exists() and not video.exists() and not artwork.exists()
    assert not service.db.one("SELECT 1 FROM media WHERE id=?", (mid,))
    assert not service.db.one("SELECT 1 FROM playlist_items WHERE media_id=?", (mid,))
    assert not service.db.one("SELECT 1 FROM cache_entries WHERE media_id=?", (mid,))
    assert not service.db.one("SELECT 1 FROM play_history WHERE media_id=?", (mid,))


def test_library_bulk_add_memberships_and_delete(service, client):
    service.import_urls(["https://www.youtube.com/playlist?list=PL1234567890"])
    ids = [row["id"] for row in service.db.all("SELECT id FROM media ORDER BY youtube_id")]
    playlist = service.library.create_playlist("Bulk list")
    other = service.library.create_playlist("Favorites")
    service.library.add(other["id"], [ids[0]])

    page = client.get("/library").text
    assert '<option value="">Select playlist</option>' in page
    assert "Add to playlist" not in page and "<th>Playlists</th>" in page
    assert 'name="pid_' not in page and 'name="single_' not in page
    assert f"/playlists/{other['slug']}" in page
    assert "None" in page

    missing = client.post(
        "/actions/library-bulk",
        data={
            "media_ids": ids[0],
            "bulk_pid": "",
            "bulk_add": "Add selected",
            "return_to": "/library?q=Song&page=1",
        },
        follow_redirects=False,
    )
    assert missing.status_code == 303
    assert missing.headers["location"].startswith("/library?q=Song&page=1&error=")
    assert "Please+select+a+playlist" in missing.headers["location"]

    added = client.post(
        "/actions/library-bulk",
        data={
            "media_ids": ids,
            "bulk_pid": playlist["id"],
            "bulk_add": "Add selected",
            "return_to": "/library",
        },
        follow_redirects=False,
    )
    assert added.status_code == 303
    assert "Added+2+tracks+to+%22Bulk+list%22" in added.headers["location"]
    page = client.get("/library").text
    assert page.count(f"/playlists/{playlist['slug']}") == 2
    assert f"/playlists/{other['slug']}" in page

    deleted = client.post(
        "/actions/library-bulk",
        data={
            "media_ids": ids[0],
            "bulk_delete": "Delete selected",
            "confirm": "yes",
            "return_to": "/library",
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert not service.db.one("SELECT 1 FROM media WHERE id=?", (ids[0],))
    assert not service.db.one("SELECT 1 FROM playlist_items WHERE media_id=?", (ids[0],))


def test_storage_hides_uncached_records_and_artwork_is_local(service, client):
    metadata = service.youtube.metadata
    service.youtube.metadata = lambda url: {
        **metadata(url),
        "_artwork_bytes": b"\xff\xd8synced artwork\xff\xd9",
    }
    service.import_urls(["https://www.youtube.com/watch?v=abcdefghijk"])
    mid = service.db.one("SELECT id FROM media")["id"]
    synced = client.get(f"/artwork/{mid}.jpg")
    assert synced.status_code == 200 and synced.content == b"\xff\xd8synced artwork\xff\xd9"
    service.cache.register(mid, "audio-high")
    assert "No cache records" in client.get("/storage").text

    path = service.cache.ensure(mid, "audio-standard")
    page = client.get("/storage").text
    assert "Audio" in page and "Temporary" in page
    artwork = client.get(f"/artwork/{mid}.jpg")
    assert artwork.status_code == 200 and artwork.content.startswith(b"\xff\xd8")
    assert f"/artwork/{mid}.jpg" in client.get(f"/library/{mid}").text
    assert "WM/Picture" in Tags(path)


def test_all_cache_clear_includes_permanent_files(service):
    service.import_urls(["https://www.youtube.com/watch?v=abcdefghijk"])
    mid = service.db.one("SELECT id FROM media")["id"]
    playlist = service.library.create_playlist("Permanent")
    service.library.add(playlist["id"], [mid])
    service.cache.pin(mid, "audio-standard", True)
    service.cache.playlist_pin(playlist["id"], "audio-standard", True)
    path = service.cache.ensure(mid, "audio-standard")

    service.cache.cleanup(mode="clear", include_permanent=True)

    assert not path.exists()
    assert service.db.one(
        "SELECT pinned,state FROM cache_entries WHERE media_id=? AND profile='audio-standard'", (mid,)
    ) == {"pinned": 0, "state": "UNCACHED"}
    assert not service.db.one("SELECT 1 FROM playlist_pins")


def test_long_pages_use_twenty_entry_pagination(service, client):
    media_ids = []
    for number in range(21):
        media_ids.append(
            service.library.import_info(
                {
                    "id": f"{number:011d}",
                    "title": f"Pagination Track {number:02d}",
                    "artist": "Page Test",
                    "duration": 60,
                }
            )
        )
        service.library.create_playlist(f"Pagination Playlist {number:02d}")
    track_list = service.library.create_playlist("Track list")
    service.library.add(track_list["id"], media_ids)
    for mid in media_ids:
        service.cache.register(mid, "audio-standard")
        service.db.execute(
            "UPDATE cache_entries SET state='CACHED',size=1 WHERE media_id=? AND profile='audio-standard'",
            (mid,),
        )

    first_library = client.get("/library").text
    second_library = client.get("/library?page=2").text
    assert "Page 1 of 2" in first_library and "Pagination Track 00" not in first_library
    assert "Page 2 of 2" in second_library and "Pagination Track 00" in second_library
    first_playlists = client.get("/playlists").text
    second_playlists = client.get("/playlists?page=2").text
    assert "Page 1 of 2" in first_playlists and "Pagination Playlist 20" not in first_playlists
    assert "Page 2 of 2" in second_playlists and "Pagination Playlist 20" in second_playlists
    assert "Page 1 of 2" in client.get(f"/playlists/{track_list['slug']}").text
    assert "Page 2 of 2" in client.get(f"/playlists/{track_list['slug']}?page=2").text
    assert "Page 1 of 2" in client.get("/storage").text
    assert "Page 2 of 2" in client.get("/storage?page=2").text


def test_status_log_paginates_and_clear_preserves_active_jobs(service, client):
    for number in range(24):
        service.db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
            (f"completed-{number:02d}", "cleanup", "{}", None, "Completed", number, number, None),
        )
    service.db.execute(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
        ("running-job", "cleanup", "{}", None, "Running", 100, 100, None),
    )
    assert "Page 1 of 2" in client.get("/status").text
    assert "Page 2 of 2" in client.get("/status?page=2").text

    response = client.post(
        "/actions/clear-log",
        data={"confirm": "yes", "return_to": "/status?page=2"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert service.db.one("SELECT COUNT(*) n FROM jobs")["n"] == 1
    assert service.db.one("SELECT state FROM jobs WHERE id='running-job'")["state"] == "Running"


def test_download_is_snapshot_and_permanent_playlist_is_dynamic(service, client):
    service.import_urls(["https://www.youtube.com/playlist?list=PL1234567890"])
    ids = [row["id"] for row in service.db.all("SELECT id FROM media ORDER BY youtube_id")]
    playlist = service.library.create_playlist("Changing mix")
    service.library.add(playlist["id"], ids[:1])
    url = f"/playlists/{playlist['slug']}/audio.asx"
    snapshot = client.get(url + "?download=1")
    assert snapshot.content.count(b"<ENTRY>") == 1
    service.library.add(playlist["id"], ids[1:])
    current = client.get(url)
    assert snapshot.content.count(b"<ENTRY>") == 1
    assert current.content.count(b"<ENTRY>") == 2
    wpl = client.get(f"/playlists/{playlist['slug']}/audio.wpl?download=1")
    assert wpl.headers["content-disposition"] == 'attachment; filename="Changing mix - Audio.wpl"'
    source = re.search(rb'src="([^"]+)"', wpl.content).group(1).decode().replace("&amp;", "&")
    path = source.split(service.config.stream_url, 1)[1]
    assert client.get(path).status_code == 200


def test_cache_miss_http_ranges_head_history(service, client):
    service.import_urls(["https://www.youtube.com/watch?v=abcdefghijk"])
    mid = service.db.one("SELECT id FROM media")["id"]
    url = f"/media/{mid}/audio"
    response = client.get(url)
    assert response.status_code == 200
    raw = response.content
    assert raw[:16].hex() == "3026b2758e66cf11a6d900aa0062ce6c"
    assert client.get(url, headers={"Range": "bytes=10-29"}).content == raw[10:30]
    assert client.get(url, headers={"Range": "bytes=-32"}).content == raw[-32:]
    assert client.get(url, headers={"Range": f"bytes={len(raw)}-"}).status_code == 416
    assert client.get(url, headers={"Range": "bytes=0-1,3-4"}).status_code == 416
    assert client.head(url).headers["content-length"] == str(len(raw))
    assert service.cache.transcoder.calls == 1
    assert not service.cache.users
    assert service.library.media(mid)["last_played"]
    assert service.library.media(mid)["request_count"] == 6
    assert client.get(f"/media/{mid}/../../etc/passwd").status_code == 404
    assert client.get(f"/media/{mid}/nonsense").status_code == 404


def unpack_frames(raw):
    result = []
    offset = 0
    while offset < len(raw):
        assert raw[offset] & 0x7F == 0x24
        kind = raw[offset + 1 : offset + 2]
        length = struct.unpack_from("<H", raw, offset + 2)[0]
        result.append((kind, raw[offset + 4 : offset + 4 + length]))
        offset += 4 + length
    assert offset == len(raw)
    return result


def test_wmsp_describe_play_seek(service, client):
    service.import_urls(["https://www.youtube.com/watch?v=abcdefghijk"])
    mid = service.db.one("SELECT id FROM media")["id"]
    path = service.cache.ensure(mid, "video-standard")
    asf = ASF.read(path)
    assert asf.packet_count > 0 and asf.index
    assert 5900 < asf.duration_ms < 6200
    assert asf.seek_packet(4500) > 0
    url = f"/media/{mid}/video"
    download = client.get(
        url, headers={"User-Agent": "NSPlayer/12.0", "Pragma": "no-cache", "Range": "bytes=0-"}
    )
    assert download.status_code == 206
    assert download.content == path.read_bytes()
    assert download.headers["content-type"] == "video/x-ms-wmv"
    describe = client.get(
        url, headers={"User-Agent": "NSPlayer/9.0", "Pragma": "no-cache, request-context=1"}
    )
    assert describe.headers["content-type"] == "application/vnd.ms.wms-hdr.asfv1"
    assert describe.headers.get("transfer-encoding") is None
    assert unpack_frames(describe.content)[0][1][8:] == asf.header
    play = client.get(
        url,
        headers=[("User-Agent", "NSPlayer/9.0"), ("Pragma", "xPlayStrm=1"), ("Pragma", "stream-time=4500")],
    )
    assert play.status_code == 200
    frames = unpack_frames(play.content)
    assert frames[0][0] == b"H" and frames[-1] == (b"E", b"\x00" * 4)
    assert struct.unpack_from("<I", frames[1][1])[0] == asf.seek_packet(4500)
    assert len(frames) == asf.packet_count - asf.seek_packet(4500) + 2
    assert service.cache.stats()["active_streams"] == 0


def test_protocol_bounds(service):
    assert byte_range("bytes=5-", 10) == (5, 9, 206)
    assert byte_range("bytes=-50", 10) == (0, 9, 206)
    assert pragmas(["stream-time=1200", "xPlayStrm=1"]) == {"stream-time": "1200", "xplaystrm": "1"}
    with pytest.raises(ValueError):
        frame(b"D", b"a" * 65528)
    path = service.cache.work / "invalid.asf"
    path.write_bytes(b"invalid")
    with pytest.raises(ValueError):
        ASF.read(path)


def test_status_does_not_expose_unreliable_active_stream_count(client):
    assert "active_streams" not in client.get("/api/status").json()


def test_legacy_layout_uses_inline_sidebar_and_table_playback_rows(service, client):
    dashboard = client.get("/").text
    assert '<div class="nav-row"><img' in dashboard
    assert '<div class="nav-row"><a' not in dashboard
    assert '<span class="brand-line"><a class="brand"' in dashboard
    assert '<span class="tagline">Modern media for classic Windows</span>' in dashboard

    service.library.import_info(
        {"id": "layout00001", "title": "Layout check", "artist": "RetroStream", "duration": 60}
    )
    library = client.get("/library").text
    assert 'class="bulk-primary"' in library and 'class="bulk-delete"' in library
    assert "Low (Legacy)" in client.get("/library/" + service.db.one("SELECT id FROM media")["id"]).text

    playlist = service.library.create_playlist("Layout check")
    detail = client.get(f"/playlists/{playlist['slug']}").text
    assert '<table class="playback-table">' in detail

    css = client.get("/static/style.css").text
    assert ".brand-icon{position:absolute" in css
    assert ".sidebar,.main{display:inline}" in css
    assert ".nav-row img{float:none;margin:0 5px 0 0;vertical-align:middle}" in css
    header_css = client.get("/static/header-alignment.css").text
    assert ".brand-line .tagline" in header_css and "vertical-align:baseline" in header_css
