import contextlib
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from retrostream.process import Processes
from retrostream.youtube import YouTube


def test_invalid_cache_recovery(service):
    mid = service.library.import_info({"id": "abcdefghijk", "title": "Track"})
    for profile, content in (("audio-standard", b"partial"), ("video-standard", b"")):
        path = service.cache.path(mid, profile)
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(content)
    service.cache.reconcile()
    assert not service.cache.path(mid, "audio-standard").exists()
    assert not service.cache.path(mid, "video-standard").exists()
    assert service.library.media(mid)["title"] == "Track"
    assert all(
        row["state"] == "FAILED"
        for row in service.cache.entries(mid)
        if row["profile"] in ("audio-standard", "video-standard")
    )


def test_generation_protection_and_stream_limit(service):
    mid = service.library.import_info({"id": "abcdefghijk", "title": "Track"})
    entered, release = threading.Event(), threading.Event()
    original = service.cache.transcoder.generate

    def slow(*args):
        entered.set()
        assert release.wait(5)
        original(*args)

    service.cache.transcoder.generate = slow
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(service.cache.ensure, mid, "audio-standard")
        assert entered.wait(2)
        service.cache.cleanup("clear")
        assert service.cache.entries(mid)[0]["state"] == "CACHING"
        release.set()
        assert future.result().exists()
    with contextlib.ExitStack() as stack:
        for _ in range(service.config.max_streams):
            stack.enter_context(service.cache.lease(mid, "audio-standard"))
        with pytest.raises(RuntimeError):
            with service.cache.lease(mid, "audio-standard"):
                pass
    assert not service.cache.users


def test_unavailable_preserves_library_and_can_retry(service):
    playlist = service.library.create_playlist("Unavailable")
    original = service.youtube.metadata
    service.youtube.metadata = lambda _: (_ for _ in ()).throw(RuntimeError("Private video"))
    with pytest.raises(RuntimeError, match="1 unavailable"):
        service.import_urls(["https://www.youtube.com/watch?v=abcdefghijk"], playlist["id"])
    item = service.library.playlist(playlist["id"])["items"][0]
    assert item["error"] == "Private video"
    service.youtube.metadata = original
    service.refresh(item["id"])
    assert service.library.media(item["id"])["error"] is None


def test_process_shutdown_and_timeout():
    processes = Processes()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(processes.run, [sys.executable, "-c", "import time; time.sleep(30)"], 60)
        deadline = time.monotonic() + 3
        while not processes.active and time.monotonic() < deadline:
            time.sleep(0.01)
        assert processes.active
        processes.close()
        assert future.result(timeout=3).returncode != 0
    with pytest.raises(RuntimeError, match="shutting down"):
        processes.run([sys.executable, "-c", "print(1)"], 1)
    with pytest.raises(subprocess.TimeoutExpired):
        Processes().run([sys.executable, "-c", "import time; time.sleep(2)"], 0.05)


def test_youtube_arguments_and_error_redaction(service):
    calls = []

    class Recorder:
        def run(self, args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 1, "", "private video signed-url=SECRET")

    youtube = YouTube(service.config, Recorder())
    with pytest.raises(RuntimeError, match="This video is private") as failure:
        youtube.metadata("https://youtu.be/abcdefghijk")
    assert "SECRET" not in str(failure.value)
    assert calls[0][-2:] == ["--", "https://www.youtube.com/watch?v=abcdefghijk"]
    assert "--ignore-config" in calls[0]
    with pytest.raises(ValueError):
        youtube.metadata("https://localhost/;echo bad")
    assert len(calls) == 1
