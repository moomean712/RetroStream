import logging
import math
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..security import safe_return, with_message

log = logging.getLogger(__name__)
PROFILE_GROUPS = {
    "audio": (("audio-standard", "Standard"), ("audio-high", "High")),
    "video": (
        ("video-low", "Low (Legacy)"),
        ("video-standard", "Standard"),
        ("video-high", "High"),
    ),
}
PAGE_SIZE = 20


def router(service, csrf):
    routes = APIRouter()
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    templates.env.filters["bytesize"] = lambda n: f"{n / 1024**2:,.1f} MiB"
    templates.env.filters["duration"] = lambda n: f"{int(n or 0) // 60}:{int(n or 0) % 60:02}"

    def render(request: Request, page: str, **context):
        token, signed = csrf.token(request)
        query = request.url.query
        return_to = request.url.path + (("?" + query) if query else "")
        response = templates.TemplateResponse(
            request=request,
            name=page + ".html",
            context={
                "page": page,
                "csrf": token,
                "config": service.config,
                "profiles": PROFILE_GROUPS,
                "return_to": return_to,
                "notice": request.query_params.get("notice"),
                "error": request.query_params.get("error"),
                "user": getattr(request.state, "user", None),
                **context,
            },
        )
        response.set_cookie("retrostream_session", signed, httponly=True, samesite="strict", max_age=43200)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'"
        )
        return response

    def set_auth_cookie(response, token: str, request: Request):
        response.set_cookie(
            "retrostream_auth",
            token,
            max_age=7 * 86400,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )

    def page_info(total: int, requested: int) -> dict:
        pages = max(1, math.ceil(total / PAGE_SIZE))
        current = min(max(1, requested), pages)
        return {
            "page": current,
            "pages": pages,
            "total": total,
            "offset": (current - 1) * PAGE_SIZE,
            "previous": current - 1 if current > 1 else None,
            "next": current + 1 if current < pages else None,
        }

    def playlists(limit: int | None = None, offset: int = 0):
        suffix = " LIMIT ? OFFSET ?" if limit is not None else ""
        args = (limit, offset) if limit is not None else ()
        return service.db.all(
            "SELECT p.*,COUNT(i.media_id) item_count FROM playlists p LEFT JOIN playlist_items i "
            "ON i.playlist_id=p.id GROUP BY p.id ORDER BY p.name" + suffix,
            args,
        )

    def enrich(items):
        for item in items:
            item["cache"] = {row["profile"]: row for row in service.cache.entries(item["id"])}
            item["cache_choice"] = {}
            for kind, options in PROFILE_GROUPS.items():
                rows = [item["cache"].get(key, {}) for key, _ in options]
                selected = next((row for row in rows if row.get("is_pinned")), None)
                selected = selected or next(
                    (row for row in rows if row.get("state") in ("CACHED", "PINNED", "CACHING")), None
                )
                item["cache_choice"][kind] = {
                    "profile": selected.get("profile")
                    if selected
                    else getattr(service.config, "default_" + kind),
                    "policy": (
                        "permanent"
                        if selected and selected.get("is_pinned")
                        else "temporary"
                        if selected and selected.get("state") in ("CACHED", "PINNED", "CACHING")
                        else "none"
                    ),
                }
        return items

    @routes.get("/setup")
    def setup(request: Request, return_to: str = "/"):
        if service.auth.has_admin():
            return RedirectResponse("/login", status_code=303)
        return render(request, "setup", return_to=safe_return(return_to))

    @routes.post("/setup", dependencies=[Depends(csrf.verify)])
    async def complete_setup(request: Request):
        form = await request.form()
        destination = safe_return(str(form.get("return_to", "/")))
        try:
            session = service.auth.create_admin(
                str(form.get("code", "")),
                str(form.get("username", "")),
                str(form.get("password", "")),
                str(form.get("confirm_password", "")),
            )
        except ValueError as exc:
            target = "/setup?" + urlencode({"return_to": destination})
            return RedirectResponse(with_message(target, str(exc), "error"), status_code=303)
        response = RedirectResponse(
            with_message(destination, "Administrator account created."), status_code=303
        )
        set_auth_cookie(response, session, request)
        return response

    @routes.get("/login")
    def login(request: Request, return_to: str = "/"):
        if not service.auth.has_admin():
            return RedirectResponse("/setup", status_code=303)
        if service.auth.username(request.cookies.get("retrostream_auth")):
            return RedirectResponse(safe_return(return_to), status_code=303)
        return render(request, "login", return_to=safe_return(return_to))

    @routes.post("/login", dependencies=[Depends(csrf.verify)])
    async def log_in(request: Request):
        form = await request.form()
        destination = safe_return(str(form.get("return_to", "/")))
        try:
            session = service.auth.login(str(form.get("username", "")), str(form.get("password", "")))
        except ValueError as exc:
            target = "/login?" + urlencode({"return_to": destination})
            return RedirectResponse(with_message(target, str(exc), "error"), status_code=303)
        service.auth.logout(request.cookies.get("retrostream_auth"))
        response = RedirectResponse(with_message(destination, "Logged on."), status_code=303)
        set_auth_cookie(response, session, request)
        return response

    @routes.post("/logout", dependencies=[Depends(csrf.verify)])
    async def log_out(request: Request):
        service.auth.logout(request.cookies.get("retrostream_auth"))
        response = RedirectResponse("/login?notice=Logged+off.", status_code=303)
        response.delete_cookie("retrostream_auth")
        return response

    @routes.get("/")
    def dashboard(request: Request):
        return render(request, "dashboard", status=service.status())

    @routes.get("/library")
    def library(request: Request, q: str = "", page: int = 1):
        search = f"%{q[:200]}%"
        total = service.db.one(
            "SELECT COUNT(*) n FROM media WHERE title LIKE ? OR artist LIKE ?", (search, search)
        )["n"]
        pagination = page_info(total, page)
        rows = service.db.all(
            "SELECT * FROM media WHERE title LIKE ? OR artist LIKE ? ORDER BY added DESC LIMIT ? OFFSET ?",
            (search, search, PAGE_SIZE, pagination["offset"]),
        )
        items = enrich(rows)
        if items:
            marks = ",".join("?" for _ in items)
            memberships = service.db.all(
                "SELECT i.media_id,p.name,p.slug FROM playlist_items i JOIN playlists p "
                f"ON p.id=i.playlist_id WHERE i.media_id IN ({marks}) ORDER BY p.name",
                tuple(item["id"] for item in items),
            )
            by_media = {item["id"]: [] for item in items}
            for membership in memberships:
                by_media[membership["media_id"]].append(membership)
            for item in items:
                item["memberships"] = by_media[item["id"]]
        return render(
            request,
            "library",
            items=items,
            playlists=playlists(),
            q=q,
            pagination=pagination,
        )

    @routes.get("/library/{mid}")
    def media_detail(request: Request, mid: str):
        item = enrich([service.library.media(mid)])[0]
        memberships = service.db.all(
            "SELECT p.name,p.slug FROM playlist_items i JOIN playlists p ON p.id=i.playlist_id "
            "WHERE i.media_id=? ORDER BY p.name",
            (mid,),
        )
        return render(
            request,
            "media",
            item=item,
            memberships=memberships,
            artwork_available=service.cache.artwork_path(mid).is_file(),
        )

    @routes.get("/artwork/{mid}.jpg")
    def artwork(mid: str):
        path = service.cache.artwork_path(mid)
        if not path.is_file():
            raise KeyError("Artwork is not available")
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @routes.get("/playlists")
    def list_playlists(request: Request, page: int = 1):
        total = service.db.one("SELECT COUNT(*) n FROM playlists")["n"]
        pagination = page_info(total, page)
        return render(
            request,
            "playlists",
            playlists=playlists(PAGE_SIZE, pagination["offset"]),
            pagination=pagination,
        )

    @routes.get("/playlists/{identifier}")
    def detail(request: Request, identifier: str, page: int = 1):
        playlist = service.library.playlist(identifier)
        total = len(playlist["items"])
        pagination = page_info(total, page)
        playlist["total_items"] = total
        playlist["items"] = playlist["items"][pagination["offset"] : pagination["offset"] + PAGE_SIZE]
        enrich(playlist["items"])
        playlist["pin_labels"] = {
            kind: [label for key, label in PROFILE_GROUPS[kind] if key in playlist["pins"]]
            for kind in PROFILE_GROUPS
        }
        playlist["cache_choice"] = {}
        for kind, options in PROFILE_GROUPS.items():
            selected = next((key for key, _ in options if key in playlist["pins"]), None)
            playlist["cache_choice"][kind] = {
                "profile": selected or getattr(service.config, "default_" + kind),
                "policy": "permanent" if selected else "temporary",
            }
        return render(request, "playlist", playlist=playlist, pagination=pagination)

    @routes.get("/add")
    def add(request: Request, playlist: str = ""):
        return render(request, "add", playlists=playlists(), selected=playlist)

    @routes.get("/storage")
    def storage(request: Request, page: int = 1):
        rows = [row for row in service.cache.entries() if row["state"] in ("CACHED", "PINNED", "CACHING")]
        pagination = page_info(len(rows), page)
        rows = rows[pagination["offset"] : pagination["offset"] + PAGE_SIZE]
        names = {row["id"]: row["title"] for row in service.db.all("SELECT id,title FROM media")}
        return render(
            request,
            "storage",
            status=service.cache.stats(),
            entries=rows,
            names=names,
            pagination=pagination,
        )

    @routes.get("/settings")
    def settings(request: Request):
        return render(request, "settings", settings=service.config.public())

    @routes.get("/account/password")
    def password(request: Request):
        return render(request, "password")

    @routes.post("/account/password", dependencies=[Depends(csrf.verify)])
    async def change_password(request: Request):
        form = await request.form()
        try:
            session = service.auth.change_password(
                str(form.get("current_password", "")),
                str(form.get("password", "")),
                str(form.get("confirm_password", "")),
            )
        except ValueError as exc:
            return RedirectResponse(with_message("/account/password", str(exc), "error"), status_code=303)
        response = RedirectResponse(with_message("/", "Password changed."), status_code=303)
        set_auth_cookie(response, session, request)
        return response

    @routes.get("/status")
    def status(request: Request, page: int = 1):
        total = service.db.one("SELECT COUNT(*) n FROM jobs")["n"]
        pagination = page_info(total, page)
        return render(
            request,
            "status",
            status=service.status(),
            jobs=service.db.all(
                "SELECT * FROM jobs ORDER BY created DESC LIMIT ? OFFSET ?",
                (PAGE_SIZE, pagination["offset"]),
            ),
            pagination=pagination,
        )

    @routes.post("/actions/{action}", dependencies=[Depends(csrf.verify)])
    async def action(request: Request, action: str):
        form = await request.form()
        pid, mid = str(form.get("pid", "")), str(form.get("mid", ""))
        profile = str(form.get("profile", service.config.default_audio))
        confirmed = form.get("confirm") == "yes"
        origin = safe_return(str(form.get("return_to", "/")))
        redirect, message = origin, "Done."
        try:
            if action == "create":
                playlist = service.library.create_playlist(str(form.get("name", "")))
                redirect = "/playlists/" + playlist["slug"]
                message = "Playlist created."
            elif action == "import":
                urls = str(form.get("urls", "")).split()
                from ..youtube import canonical_url

                if not urls or len(urls) > 100:
                    raise ValueError("Supply 1–100 YouTube URLs")
                for url in urls:
                    canonical_url(url)
                if form.get("new_name"):
                    pid = service.library.create_playlist(str(form["new_name"]))["id"]
                service.queue_import(urls, pid or None)
                message = "Media import queued."
            elif action in (
                "rename",
                "delete",
                "remove",
                "move",
                "add-items",
                "playlist-cache",
                "playlist-pin",
                "playlist-policy",
                "playlist-clear",
            ):
                playlist = service.library.playlist(pid)
                if origin == "/":
                    redirect = "/playlists/" + playlist["slug"]
                if action == "rename":
                    service.library.rename(pid, str(form.get("name", "")))
                    message = "Playlist renamed."
                elif action == "delete":
                    if not confirmed:
                        raise ValueError("Check the confirmation box before deleting the playlist")
                    service.db.execute("DELETE FROM playlists WHERE id=?", (pid,))
                    redirect, message = "/playlists", "Playlist deleted."
                elif action == "remove":
                    service.db.execute(
                        "DELETE FROM playlist_items WHERE playlist_id=? AND media_id=?", (pid, mid)
                    )
                    message = "Removed from playlist."
                elif action == "move":
                    ids = [row["id"] for row in playlist["items"]]
                    if mid not in ids:
                        raise ValueError("Item is not in playlist")
                    position = ids.index(mid)
                    delta = -1 if form.get("direction") == "up" else 1
                    target = max(0, min(len(ids) - 1, position + delta))
                    ids[position], ids[target] = ids[target], ids[position]
                    service.library.reorder(pid, ids)
                    message = "Playlist order updated."
                elif action == "add-items":
                    service.library.add(pid, [str(value) for value in form.getlist("media_ids")])
                    service.prepare_pins()
                    message = f"Added to {playlist['name']}."
                elif action == "playlist-cache":
                    service.playlist_cache(pid, profile)
                    message = f"{profile.split('-', 1)[0].title()} playlist caching queued."
                elif action == "playlist-pin":
                    enabled = form.get("enabled") == "yes"
                    service.cache.playlist_pin(pid, profile, enabled)
                    service.prepare_pins()
                    message = "Playlist cache preference updated."
                elif action == "playlist-policy":
                    kind = str(form.get("kind", ""))
                    policy = str(form.get("policy", ""))
                    valid_profiles = {key for key, _ in PROFILE_GROUPS.get(kind, ())}
                    if profile not in valid_profiles or policy not in ("none", "temporary", "permanent"):
                        raise ValueError("Invalid playlist cache selection")
                    media_ids = [row["id"] for row in playlist["items"]]
                    if policy == "none":
                        for key in valid_profiles:
                            service.cache.playlist_pin(pid, key, False)
                        service.jobs.submit(
                            "cleanup",
                            {"mode": "clear", "kind": kind, "media_ids": media_ids},
                        )
                        message = f"Temporary {kind} cache removal queued."
                    else:
                        service.playlist_cache(pid, profile, policy == "permanent")
                        message = f"Playlist {kind} will be cached {policy}."
                elif action == "playlist-clear":
                    if not confirmed:
                        raise ValueError("Confirm removal of cached media")
                    service.jobs.submit(
                        "cleanup",
                        {
                            "mode": "clear",
                            "kind": str(form.get("kind", "all")),
                            "media_ids": [row["id"] for row in playlist["items"]],
                        },
                    )
                    message = "Playlist cache clearing queued."
                log.info("playlist_modified", extra={"playlist": pid, "action": action})
            elif action == "library-bulk":
                media_ids = list(dict.fromkeys(str(value) for value in form.getlist("media_ids")))
                if not media_ids or len(media_ids) > PAGE_SIZE:
                    raise ValueError("Select 1–20 tracks from this page")
                if form.get("bulk_add"):
                    selected_pid = str(form.get("bulk_pid", ""))
                    if not selected_pid:
                        raise ValueError("Please select a playlist.")
                    playlist = service.library.playlist(selected_pid)
                    service.library.add(selected_pid, media_ids)
                    service.prepare_pins()
                    message = f'Added {len(media_ids)} tracks to "{playlist["name"]}".'
                elif form.get("bulk_delete"):
                    if not confirmed:
                        raise ValueError("Confirm permanent deletion of the selected tracks")
                    for media_id in media_ids:
                        service.cache.delete_media(media_id)
                    redirect, message = "/library", f"Deleted {len(media_ids)} tracks permanently."
                else:
                    raise ValueError("Choose a bulk action")
            elif action == "cache":
                service.queue_cache(mid, profile)
                message = f"{profile.split('-', 1)[0].title()} caching queued."
            elif action == "pin":
                enabled = form.get("enabled") == "yes"
                if enabled:
                    service.queue_cache(mid, profile, True)
                else:
                    service.cache.pin(mid, profile, False)
                message = "Cache preference updated."
            elif action == "cache-policy":
                item = service.library.media(mid)
                del item
                kind = str(form.get("kind", ""))
                policy = str(form.get("policy", ""))
                valid_profiles = {key for key, _ in PROFILE_GROUPS.get(kind, ())}
                if profile not in valid_profiles or policy not in ("none", "temporary", "permanent"):
                    raise ValueError("Invalid cache selection")
                if policy == "none":
                    for key in valid_profiles:
                        service.cache.pin(mid, key, False)
                    service.jobs.submit(
                        "cleanup",
                        {"mode": "clear", "kind": kind, "media_ids": [mid]},
                    )
                    message = f"{kind.title()} cache removal queued."
                else:
                    service.queue_cache(mid, profile, policy == "permanent")
                    message = f"{kind.title()} will be cached {policy}."
            elif action == "delete-media":
                if not confirmed:
                    raise ValueError("Confirm permanent deletion from the library")
                service.cache.delete_media(mid)
                redirect, message = "/library", "Track permanently deleted from the library."
            elif action == "refresh":
                service.library.media(mid)
                service.jobs.submit("refresh", {"mid": mid}, f"refresh:{mid}")
                message = "Metadata refresh queued."
            elif action == "cleanup":
                service.jobs.submit("cleanup", {"mode": "unused"}, "manual-cleanup")
                message = "Cache cleanup queued."
            elif action == "clear":
                if not confirmed:
                    raise ValueError("Check the confirmation box before clearing cache")
                kind = str(form.get("kind", "all"))
                if kind not in ("all", "audio", "video"):
                    raise ValueError("Invalid cache kind")
                include_permanent = form.get("scope") == "all"
                service.jobs.submit(
                    "cleanup",
                    {"mode": "clear", "kind": kind, "include_permanent": include_permanent},
                )
                message = (
                    "All cache clearing queued." if include_permanent else "Temporary cache clearing queued."
                )
            elif action == "clear-log":
                if not confirmed:
                    raise ValueError("Confirm clearing the completed task log")
                service.db.execute("DELETE FROM jobs WHERE state IN ('Completed','Failed')")
                redirect, message = "/status", "Completed task log cleared."
            elif action == "retry":
                service.retry(str(form.get("jid", "")))
                message = "Task queued again."
            else:
                raise ValueError("Unknown action")
        except (ValueError, KeyError) as exc:
            return RedirectResponse(with_message(origin, str(exc).strip("'"), "error"), status_code=303)
        return RedirectResponse(with_message(redirect, message), status_code=303)

    return routes
