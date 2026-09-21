import asyncio
import logging
import re
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from .asf import ASF
from .wmsp import header_packets, play_packets, pragmas

log = logging.getLogger(__name__)


class LeasedResponse(StreamingResponse):
    def __init__(self, *args, lease, **kwargs):
        super().__init__(*args, **kwargs)
        self.lease = lease

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.lease.__exit__(None, None, None)


def byte_range(value: str | None, size: int) -> tuple[int, int, int]:
    if not value:
        return 0, size - 1, 200
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or not any(match.groups()):
        raise ValueError("Only a single byte range is supported")
    left, right = match.groups()
    if not left:
        length = int(right)
        if length <= 0:
            raise ValueError("Invalid suffix range")
        return max(0, size - length), size - 1, 206
    start, end = int(left), min(int(right), size - 1) if right else size - 1
    if start > end or start >= size:
        raise ValueError("Range outside media")
    return start, end, 206


def file_chunks(path, start, end):
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining:
            data = file.read(min(64 * 1024, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def router(service):
    routes = APIRouter()

    @routes.api_route("/media/{mid}/{mode}", methods=["GET", "HEAD"])
    @routes.api_route("/media/{mid}/{mode}/{filename}", methods=["GET", "HEAD"])
    async def media(request: Request, mid: str, mode: str, filename: str | None = None):
        try:
            service.library.media(mid)
            fallback = {"audio": service.config.default_audio, "video": service.config.default_video}.get(
                mode
            )
            profile = service.cache.active_profile(mid, mode, fallback) if fallback else mode
            path = service.cache.path(mid, profile)
        except (KeyError, ValueError):
            raise HTTPException(404, "Unknown media or representation") from None
        lease = service.cache.lease(mid, profile)
        try:
            lease.__enter__()
        except RuntimeError as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "10"}) from None
        transferred = False
        try:
            now = time.time()
            with service.db.connect() as db:
                db.execute(
                    "UPDATE media SET last_accessed=?,request_count=request_count+1 WHERE id=?", (now, mid)
                )
                history = db.execute(
                    "INSERT INTO play_history(media_id,profile,requested) VALUES(?,?,?)", (mid, profile, now)
                ).lastrowid
            if not path.exists():
                log.info("cache_miss", extra={"media": mid, "profile": profile})
                jid = service.queue_cache(mid, profile)
                deadline = time.monotonic() + service.config.preparation_timeout
                while not path.exists():
                    job = service.db.one("SELECT state,error FROM jobs WHERE id=?", (jid,))
                    if job["state"] == "Failed":
                        raise HTTPException(503, job["error"], headers={"Retry-After": "30"})
                    if time.monotonic() > deadline:
                        raise HTTPException(
                            503,
                            "Media is still preparing; reopen the playlist shortly",
                            headers={"Retry-After": "30"},
                        )
                    if await request.is_disconnected():
                        raise HTTPException(499, "Client disconnected during preparation")
                    await asyncio.sleep(0.2)
            service.db.execute(
                "UPDATE cache_entries SET last_accessed=? WHERE media_id=? AND profile=?", (now, mid, profile)
            )
            headers = {"Cache-Control": "no-cache", "Accept-Ranges": "bytes"}
            pragma = pragmas(request.headers.getlist("pragma"))
            # NSPlayer also downloads ordinary ASF files, including Range requests.
            # Only protocol negotiation tokens identify an MMSH request.
            wmsp = any(
                key in pragma
                for key in (
                    "xplaystrm",
                    "stream-time",
                    "request-context",
                    "stream-switch-entry",
                    "xplaynextentry",
                    "pipeline-request",
                )
            )
            if wmsp:
                asf = ASF.read(path)
                headers.update(
                    {
                        "Server": "Cougar/4.1.0.3923",
                        "Pragma": 'no-cache, client-id=1, features="seekable", timeout=60000',
                        "Connection": "close",
                    }
                )
                if any(key in pragma for key in ("xplaynextentry", "pipeline-request")):
                    raise HTTPException(400, "Server-side playlists and pipelining are unsupported")
                play = pragma.get("xplaystrm") == "1" or "stream-switch-entry" in pragma
                if not play:
                    body = header_packets(asf)
                    return Response(
                        body if request.method != "HEAD" else b"",
                        media_type="application/vnd.ms.wms-hdr.asfv1",
                        headers={**headers, "Content-Length": str(len(body))},
                    )
                try:
                    start_ms = int(pragma.get("stream-time", "0"))
                    if start_ms == 4294967295:
                        start_ms = 0
                    if start_ms < 0:
                        raise ValueError()
                except ValueError:
                    raise HTTPException(400, "Invalid stream-time") from None
                start = asf.seek_packet(start_ms)
                chunks = play_packets(asf, start)
                headers["Content-Length"] = str(
                    len(header_packets(asf)) + (asf.packet_count - start) * (asf.packet_size + 12) + 8
                )
                content_type, status = "application/x-mms-framed", 200
            else:
                size = path.stat().st_size
                etag = f'"{size:x}-{path.stat().st_mtime_ns:x}"'
                headers["ETag"] = etag
                requested_range = request.headers.get("range")
                if request.headers.get("if-range") and request.headers["if-range"] != etag:
                    requested_range = None
                try:
                    start, end, status = byte_range(requested_range, size)
                except ValueError:
                    raise HTTPException(
                        416, "Invalid range", headers={"Content-Range": f"bytes */{size}"}
                    ) from None
                headers["Content-Length"] = str(end - start + 1)
                if status == 206:
                    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
                chunks = file_chunks(path, start, end)
                content_type = "audio/x-ms-wma" if profile.startswith("audio") else "video/x-ms-wmv"
            if request.method == "HEAD":
                return Response(headers=headers, media_type=content_type, status_code=status)
            service.db.execute("UPDATE media SET last_played=? WHERE id=?", (time.time(), mid))
            service.db.execute("UPDATE play_history SET success=1 WHERE id=?", (history,))
            log.info(
                "stream_request",
                extra={"media": mid, "profile": profile, "protocol": "wmsp" if wmsp else "http"},
            )
            response = LeasedResponse(
                chunks, lease=lease, headers=headers, media_type=content_type, status_code=status
            )
            transferred = True
            return response
        finally:
            if not transferred:
                lease.__exit__(None, None, None)

    return routes
