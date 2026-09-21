import shutil
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from retrostream.service import Service
from retrostream.transcoder import PROFILES


def imported(service):
    service.import_urls(["https://www.youtube.com/watch?v=abcdefghijk"])
    return service.db.one("SELECT id FROM media")["id"]


def test_cache_concurrency_and_separate_profiles(service):
    mid = imported(service)
    with ThreadPoolExecutor(4) as pool:
        paths = list(pool.map(lambda _: service.cache.ensure(mid, "audio-standard"), range(4)))
    assert len(set(paths)) == 1 and service.cache.transcoder.calls == 1
    service.cache.ensure(mid, "video-standard")
    assert service.cache.transcoder.calls == 2
    assert service.cache.stats()["cached"] == 2
    assert service.cache.ensure(mid, "audio-standard").exists()
    assert service.cache.transcoder.calls == 2


def test_changed_video_low_profile_invalidates_only_legacy_cache(service):
    mid = imported(service)
    audio = service.cache.ensure(mid, "audio-standard")
    stale_low = service.cache.ensure(mid, "video-low")
    for profile in ("video-standard", "video-high"):
        service.cache.register(mid, profile)
    service.db.execute(
        "UPDATE cache_entries SET profile_version=1 WHERE media_id=? AND profile='video-low'",
        (mid,),
    )

    service.cache.reconcile()

    assert audio.exists()
    assert not stale_low.exists()
    assert service.db.one(
        "SELECT state,profile_version FROM cache_entries WHERE media_id=? AND profile='video-low'",
        (mid,),
    ) == {"state": "UNCACHED", "profile_version": 2}
    assert all(
        service.db.one(
            "SELECT profile_version FROM cache_entries WHERE media_id=? AND profile=?",
            (mid, profile),
        )["profile_version"]
        == 1
        for profile in ("video-standard", "video-high")
    )
    regenerated = service.cache.ensure(mid, "video-low")
    assert regenerated.exists()
    assert (
        service.db.one(
            "SELECT profile_version FROM cache_entries WHERE media_id=? AND profile='video-low'",
            (mid,),
        )["profile_version"]
        == 2
    )


def test_quality_replacement_is_safe_and_preserves_state(service):
    mid = imported(service)
    audio_standard = service.cache.ensure(mid, "audio-standard")
    video_standard = service.cache.ensure(mid, "video-standard")
    service.cache.pin(mid, "audio-standard", True)
    original_generate = service.cache.transcoder.generate

    def fail_high(media, profile, work, target):
        if profile is PROFILES["audio-high"]:
            raise RuntimeError("replacement failed")
        return original_generate(media, profile, work, target)

    service.cache.transcoder.generate = fail_high
    with pytest.raises(RuntimeError, match="replacement failed"):
        service.cache.ensure(mid, "audio-high")
    assert audio_standard.exists()
    assert service.cache.active_profile(mid, "audio") == "audio-standard"
    assert service.cache.pinned(mid, "audio-standard")
    assert video_standard.exists()

    service.cache.transcoder.generate = original_generate
    audio_high = service.cache.ensure(mid, "audio-high")
    assert audio_high.exists() and not audio_standard.exists()
    assert service.cache.pinned(mid, "audio-high")
    assert video_standard.exists()
    assert not service.cache.pinned(mid, "video-standard")
    video_high = service.cache.ensure(mid, "video-high")
    assert video_high.exists() and not video_standard.exists()
    assert audio_high.exists()
    assert (
        service.db.one(
            "SELECT COUNT(*) n FROM cache_entries WHERE media_id=? AND profile LIKE 'audio-%' "
            "AND state='CACHED'",
            (mid,),
        )["n"]
        == 1
    )

    # Recovery honors the committed active preference instead of reviving a
    # superseded representation found on disk after an interrupted cleanup.
    stale = service.cache.path(mid, "audio-standard")
    shutil.copyfile(audio_high, stale)
    service.db.execute(
        "UPDATE cache_entries SET state='CACHED',size=?,last_accessed=? "
        "WHERE media_id=? AND profile='audio-standard'",
        (stale.stat().st_size, time.time() + 10, mid),
    )
    service.cache.reconcile()
    assert audio_high.exists() and not stale.exists()
    assert service.cache.stats()["total"] == audio_high.stat().st_size + video_high.stat().st_size
    assert (
        service.db.one(
            "SELECT COUNT(*) n FROM cache_entries WHERE media_id=? AND profile LIKE 'video-%' "
            "AND state='CACHED'",
            (mid,),
        )["n"]
        == 1
    )


def test_temporary_replacement_and_shared_playlist_policy(service):
    mid = imported(service)
    first = service.library.create_playlist("First")
    second = service.library.create_playlist("Second")
    for playlist in (first, second):
        service.library.add(playlist["id"], [mid])

    old = service.cache.ensure(mid, "audio-standard", False)
    service.cache.playlist_pin(first["id"], "audio-standard", True)
    original_generate = service.cache.transcoder.generate

    def fail_high(media, profile, work, target):
        if profile is PROFILES["audio-high"]:
            raise RuntimeError("playlist replacement failed")
        return original_generate(media, profile, work, target)

    service.cache.transcoder.generate = fail_high
    with pytest.raises(RuntimeError, match="playlist replacement failed"):
        service.playlist_replace(second["id"], "audio-high", True)
    assert old.exists()
    assert service.cache.active_profile(mid, "audio") == "audio-standard"
    assert service.db.one(
        "SELECT 1 FROM playlist_pins WHERE playlist_id=? AND profile='audio-standard'",
        (first["id"],),
    )

    service.cache.transcoder.generate = original_generate
    service.playlist_replace(second["id"], "audio-high", True)
    current = service.cache.path(mid, "audio-high")
    assert current.exists() and not old.exists()
    assert service.cache.active_profile(mid, "audio") == "audio-high"
    assert service.cache.pinned(mid, "audio-high")

    # Conflicting playlist declarations do not create two physical copies. The
    # latest successful explicit request is the one active representation.
    service.prepare_pins()
    assert not service.db.one("SELECT 1 FROM jobs WHERE state='Queued'")
    assert sum(service.cache.path(mid, profile).exists() for profile in ("audio-standard", "audio-high")) == 1

    service.cache.playlist_pin(first["id"], "audio-standard", False)
    service.cache.playlist_pin(second["id"], "audio-high", False)
    service.cache.ensure(mid, "audio-standard", False)
    assert not service.cache.pinned(mid, "audio-standard")
    assert not current.exists()


def test_pins_active_streams_and_lru(service):
    mid = imported(service)
    old = service.cache.ensure(mid, "audio-standard")
    service.cache.pin(mid, "audio-standard", True)
    with service.cache.lease(mid, "audio-standard"):
        current = service.cache.ensure(mid, "audio-high")
        assert old.exists() and current.exists()
        service.cache.ensure(mid, "video-low")
        service.cache.cleanup("clear")
        assert old.exists() and current.exists()
        assert not service.cache.path(mid, "video-low").exists()
    assert not old.exists() and current.exists()
    assert service.cache.pinned(mid, "audio-high")
    assert service.library.media(mid)


def test_reference_pins_and_restart(service):
    mid = imported(service)
    playlists = [service.library.create_playlist(name) for name in ("One", "Two")]
    for playlist in playlists:
        service.library.add(playlist["id"], [mid])
        service.cache.playlist_pin(playlist["id"], "audio-standard", True)
    path = service.cache.ensure(mid, "audio-standard")
    service.cache.playlist_pin(playlists[0]["id"], "audio-standard", False)
    service.cache.cleanup("clear")
    assert path.exists()
    work = service.cache.work / "rs-incomplete"
    work.mkdir()
    (work / "partial").write_bytes(b"bad")
    service.queue_cache(mid, "video-standard")
    restarted = Service(service.config, service.youtube, service.cache.transcoder)
    restarted.cache.reconcile()
    assert path.exists() and not work.exists()
    assert restarted.cache.pinned(mid, "audio-standard")
    assert restarted.db.one("SELECT state FROM jobs")["state"] == "Failed"
    assert len(restarted.library.playlist(playlists[0]["slug"])["items"]) == 1


def test_retention_and_pressure(service):
    mid = imported(service)
    service.cache.ensure(mid, "audio-high")
    service.cache.ensure(mid, "video-low")
    service.db.execute("UPDATE cache_entries SET last_accessed=1 WHERE profile='audio-high'")
    service.cache.cleanup("automatic")
    assert not service.cache.path(mid, "audio-high").exists()
    # Simulate usage crossing the configured high water mark; choose oldest eligible object first.
    service.cache.ensure(mid, "audio-high")
    service.db.execute("UPDATE cache_entries SET size=1500000 WHERE state='CACHED'")
    service.db.execute(
        "UPDATE cache_entries SET last_accessed=? WHERE profile='audio-high'", (time.time() - 60,)
    )
    service.cache.cleanup("automatic")
    assert not service.cache.path(mid, "audio-high").exists()
    assert service.cache.path(mid, "video-low").exists()


def test_jobs_success_failure_deduplication(service):
    mid = imported(service)
    a = service.queue_cache(mid, "audio-standard")
    assert a == service.queue_cache(mid, "audio-standard")
    service.jobs.handlers["bad"] = lambda: (_ for _ in ()).throw(ValueError("Expected failure"))
    b = service.jobs.submit("bad", {})
    service.jobs.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            rows = service.db.all("SELECT state FROM jobs WHERE id IN (?,?)", (a, b))
            if all(row["state"] in ("Completed", "Failed") for row in rows):
                break
            time.sleep(0.05)
        assert service.db.one("SELECT state FROM jobs WHERE id=?", (a,))["state"] == "Completed"
        assert service.db.one("SELECT error FROM jobs WHERE id=?", (b,))["error"] == "Expected failure"
    finally:
        service.jobs.close()


def test_playlist_import_and_unavailable_retry(service):
    playlist = service.library.create_playlist("Imported")
    service.import_urls(["https://www.youtube.com/playlist?list=PL1234567890"], playlist["id"])
    service.import_urls(["https://www.youtube.com/watch?v=abcdefghijk"], playlist["id"])
    assert len(service.library.playlist(playlist["id"])["items"]) == 2
