"""JSON API. Mutation endpoints require the same CSRF session as HTML forms."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field


class Name(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class Import(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=100)
    playlist_id: str | None = None


class Items(BaseModel):
    media_ids: list[str] = Field(max_length=10000)


class Representation(BaseModel):
    profile: str
    enabled: bool = True


class Clear(BaseModel):
    kind: str = "all"
    confirm: bool = False


def router(service, csrf, authenticate):
    routes = APIRouter(prefix="/api", dependencies=[Depends(authenticate), Depends(csrf)])

    @routes.get("/media")
    def media(offset: int = 0, limit: int = 100):
        return service.db.all(
            "SELECT * FROM media ORDER BY added DESC LIMIT ? OFFSET ?",
            (max(1, min(limit, 500)), max(0, offset)),
        )

    @routes.post("/media/import", status_code=202)
    def import_media(body: Import):
        return {"job_id": service.queue_import(body.urls, body.playlist_id)}

    @routes.get("/playlists")
    def playlists():
        return service.db.all(
            "SELECT p.*,COUNT(i.media_id) item_count FROM playlists p LEFT JOIN playlist_items i "
            "ON i.playlist_id=p.id GROUP BY p.id ORDER BY p.name"
        )

    @routes.post("/playlists", status_code=201)
    def create(body: Name):
        return service.library.create_playlist(body.name)

    @routes.get("/playlists/{pid}")
    def detail(pid: str):
        return service.library.playlist(pid)

    @routes.patch("/playlists/{pid}")
    def rename(pid: str, body: Name):
        service.library.rename(pid, body.name)
        return service.library.playlist(pid)

    @routes.delete("/playlists/{pid}")
    def delete(pid: str, confirm: bool = False):
        if not confirm:
            raise ValueError("Set confirm=true to delete the playlist")
        service.library.playlist(pid)
        service.db.execute("DELETE FROM playlists WHERE id=?", (pid,))
        return {"deleted": True}

    @routes.post("/playlists/{pid}/items")
    def add(pid: str, body: Items):
        service.library.add(pid, body.media_ids)
        service.prepare_pins()
        return service.library.playlist(pid)

    @routes.delete("/playlists/{pid}/items/{mid}")
    def remove(pid: str, mid: str):
        service.library.playlist(pid)
        service.db.execute("DELETE FROM playlist_items WHERE playlist_id=? AND media_id=?", (pid, mid))
        return {"removed": True}

    @routes.post("/playlists/{pid}/reorder")
    def reorder(pid: str, body: Items):
        service.library.playlist(pid)
        service.library.reorder(pid, body.media_ids)
        return service.library.playlist(pid)

    @routes.post("/playlists/{pid}/cache", status_code=202)
    def playlist_cache(pid: str, body: Representation):
        return {"job_ids": service.playlist_cache(pid, body.profile)}

    @routes.post("/playlists/{pid}/pin", status_code=202)
    def playlist_pin(pid: str, body: Representation):
        if body.enabled:
            service.playlist_cache(pid, body.profile, True)
        else:
            service.cache.playlist_pin(pid, body.profile, False)
        return {"pinned": body.enabled}

    @routes.get("/cache")
    def cache():
        return {"stats": service.cache.stats(), "entries": service.cache.entries()}

    @routes.post("/media/{mid}/cache", status_code=202)
    def prepare(mid: str, body: Representation):
        return {"job_id": service.queue_cache(mid, body.profile)}

    @routes.post("/media/{mid}/pin")
    def pin(mid: str, body: Representation):
        if body.enabled:
            service.queue_cache(mid, body.profile, True)
        else:
            service.cache.pin(mid, body.profile, False)
        return {"pinned": body.enabled}

    @routes.post("/media/{mid}/refresh", status_code=202)
    def refresh(mid: str):
        service.library.media(mid)
        return {"job_id": service.jobs.submit("refresh", {"mid": mid}, f"refresh:{mid}")}

    @routes.post("/cache/cleanup", status_code=202)
    def cleanup():
        return {"job_id": service.jobs.submit("cleanup", {"mode": "unused"}, "manual-cleanup")}

    @routes.post("/cache/clear", status_code=202)
    def clear(body: Clear):
        if not body.confirm or body.kind not in ("all", "audio", "video"):
            raise ValueError("Choose audio/video/all and confirm the deletion")
        return {"job_id": service.jobs.submit("cleanup", {"mode": "clear", "kind": body.kind})}

    @routes.get("/jobs")
    def jobs():
        return service.db.all("SELECT * FROM jobs ORDER BY created DESC LIMIT 100")

    @routes.post("/jobs/{jid}/retry", status_code=202)
    def retry(jid: str):
        return {"job_id": service.retry(jid)}

    @routes.get("/status")
    def status():
        return service.status()

    @routes.get("/settings")
    def settings():
        return service.config.public()

    return routes
