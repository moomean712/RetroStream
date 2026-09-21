import re
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api import router as api_router
from .config import Config
from .frontend import router as frontend_router
from .security import CSRF, AuthGate, BodyLimit
from .service import Service
from .streaming.asx import generate
from .streaming.http import router as stream_router
from .streaming.wpl import generate as generate_wpl


def playlist_filename(name: str, mode: str, extension: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    plain = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", plain).strip(" .")
    plain = re.sub(r"\s+", " ", plain)[:100].rstrip(" .") or "Playlist"
    return f"{plain} - {mode.title()}.{extension}"


def create_app(config: Config | None = None, service: Service | None = None, manage_lifecycle: bool = True):
    service = service or Service(config or Config())

    @asynccontextmanager
    async def lifespan(app):
        if manage_lifecycle:
            service.start()
        try:
            yield
        finally:
            if manage_lifecycle:
                service.close()

    app = FastAPI(title="RetroStream", version="0.1.0", lifespan=lifespan)
    app.state.service = service
    csrf = CSRF(service.db)
    app.add_middleware(BodyLimit)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=[service.config.hostname, "localhost", "127.0.0.1"]
    )
    app.add_middleware(AuthGate, auth=service.auth)

    @app.exception_handler(KeyError)
    async def missing(request: Request, exc: KeyError):
        return JSONResponse({"detail": str(exc).strip("'")}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/healthz", include_in_schema=False)
    def health():
        return {"status": "ok"}

    @app.get("/api/csrf")
    def csrf_token(request: Request):
        token, signed = csrf.token(request)
        response = JSONResponse({"csrf_token": token}, headers={"Cache-Control": "no-store"})
        response.set_cookie("retrostream_session", signed, httponly=True, samesite="strict", max_age=43200)
        return response

    @app.get("/playlists/{identifier}/{mode}.asx")
    def playlist(identifier: str, mode: str, download: bool = False):
        item = service.library.playlist(identifier)
        headers = {"Cache-Control": "no-cache, no-store"}
        if download:
            headers["Content-Disposition"] = (
                f'attachment; filename="{playlist_filename(item["name"], mode, "asx")}"'
            )
        return Response(
            generate(item, mode, service.config.stream_url),
            media_type="video/x-ms-asf",
            headers=headers,
        )

    @app.get("/playlists/{identifier}/{mode}.wpl")
    def wpl_playlist(identifier: str, mode: str, download: bool = False):
        item = service.library.playlist(identifier)
        headers = {"Cache-Control": "no-cache, no-store"}
        if download:
            headers["Content-Disposition"] = (
                f'attachment; filename="{playlist_filename(item["name"], mode, "wpl")}"'
            )
        return Response(
            generate_wpl(item, mode, service.config.stream_url),
            media_type="application/vnd.ms-wpl",
            headers=headers,
        )

    app.include_router(api_router(service, csrf.verify, service.auth.require))
    app.include_router(frontend_router(service, csrf))
    app.include_router(stream_router(service))
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "frontend" / "static"), name="static")
    return app


def streaming_app(service: Service):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.include_router(stream_router(service))
    return app
