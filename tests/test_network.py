"""Exercise the wire with FFmpeg's independent MMSH demuxer, over real TCP."""

import contextlib
import os
import socket
import subprocess
import threading
import time

import uvicorn

from retrostream.app import streaming_app


@contextlib.contextmanager
def running_server(service):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(streaming_app(service), log_level="error", server_header=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


def test_independent_mmsh_client(service, ffmpeg):
    service.import_urls(["https://www.youtube.com/watch?v=abcdefghijk"])
    mid = service.db.one("SELECT id FROM media")["id"]
    for profile in ("audio-standard", "video-standard"):
        service.cache.ensure(mid, profile)
    with running_server(service) as port:
        for mode in ("audio", "video"):
            for seek in ([], ["-ss", "4"]):
                args = [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "info",
                    *seek,
                    "-i",
                    f"mmsh://127.0.0.1:{port}/media/{mid}/{mode}",
                    "-t",
                    "1",
                    "-f",
                    "null",
                    "-",
                ]
                environment = {
                    k: v
                    for k, v in os.environ.items()
                    if k.lower() not in ("http_proxy", "https_proxy", "all_proxy")
                }
                result = subprocess.run(args, capture_output=True, timeout=15, check=False, env=environment)
                diagnostic = result.stderr.decode(errors="replace")
                assert result.returncode == 0, diagnostic
                assert "Output file is empty" not in diagnostic, diagnostic
                assert "wmav2" in diagnostic, diagnostic
                if mode == "video":
                    assert "wmv2" in diagnostic, diagnostic
    assert not service.cache.users
