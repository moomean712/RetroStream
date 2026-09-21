"""Signed same-origin CSRF sessions, with a bounded body for all admin requests."""

import hmac
import secrets
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.responses import JSONResponse, RedirectResponse


def safe_return(value: str | None, fallback: str = "/") -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return fallback
    parsed = urlsplit(value)
    decoded_path = unquote(parsed.path)
    if (
        parsed.scheme
        or parsed.netloc
        or decoded_path.startswith("//")
        or "\\" in decoded_path
        or any(ord(char) < 32 for char in value + decoded_path)
    ):
        return fallback
    return urlunsplit(("", "", parsed.path, parsed.query, parsed.fragment))


def with_message(value: str | None, message: str, kind: str = "notice", fallback: str = "/") -> str:
    target = urlsplit(safe_return(value, fallback))
    query = [(key, val) for key, val in parse_qsl(target.query, keep_blank_values=True) if key != kind]
    query.append((kind, message))
    return urlunsplit(("", "", target.path, urlencode(query), target.fragment))


class AuthGate:
    """Protect management HTML and API while leaving legacy playback public."""

    def __init__(self, app, auth):
        self.app, self.auth = app, auth

    @staticmethod
    def public(path: str) -> bool:
        if path in ("/healthz", "/login", "/setup", "/api/csrf", "/favicon.ico"):
            return True
        if path.startswith(("/static/", "/media/")):
            return True
        return path.startswith("/playlists/") and path.endswith((".asx", ".wpl"))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.public(scope.get("path", "")):
            return await self.app(scope, receive, send)
        request = Request(scope)
        username = self.auth.username(request.cookies.get("retrostream_auth"))
        if username:
            scope.setdefault("state", {})["user"] = username
            return await self.app(scope, receive, send)
        path = scope.get("path", "/")
        if path.startswith("/api/"):
            return await JSONResponse({"detail": "Administrator login required"}, status_code=401)(
                scope, receive, send
            )
        destination = "/setup" if not self.auth.has_admin() else "/login"
        if scope.get("method") in ("GET", "HEAD"):
            query = scope.get("query_string", b"").decode("latin-1")
            return_to = path + (("?" + query) if query else "")
            destination += "?return_to=" + quote(return_to, safe="")
        return await RedirectResponse(destination, status_code=303)(scope, receive, send)


class CSRF:
    def __init__(self, db):
        with db.connect() as conn:
            conn.execute("INSERT OR IGNORE INTO settings VALUES('csrf_secret',?)", (secrets.token_hex(32),))
            secret = conn.execute("SELECT value FROM settings WHERE key='csrf_secret'").fetchone()[0]
        self.signer = URLSafeTimedSerializer(secret, salt="retrostream-csrf")

    def token(self, request: Request) -> tuple[str, str]:
        signed = request.cookies.get("retrostream_session", "")
        try:
            token = self.signer.loads(signed, max_age=43200)
        except (BadSignature, SignatureExpired):
            token = secrets.token_hex(32)
            signed = self.signer.dumps(token)
        return token, signed

    async def verify(self, request: Request):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        try:
            token = self.signer.loads(request.cookies.get("retrostream_session", ""), max_age=43200)
        except (BadSignature, SignatureExpired):
            raise HTTPException(403, "Open a RetroStream page to establish a CSRF session") from None
        provided = request.headers.get("x-csrf-token", "")
        if not provided and request.headers.get("content-type", "").startswith(
            "application/x-www-form-urlencoded"
        ):
            form = await request.form()
            provided = str(form.get("csrf", ""))
        if not hmac.compare_digest(token, provided):
            raise HTTPException(403, "Invalid CSRF token; reload the form")


class BodyLimit:
    def __init__(self, app, limit: int = 128 * 1024):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD"):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            body.extend(event.get("body", b""))
            if len(body) > self.limit:
                await send({"type": "http.response.start", "status": 413, "headers": []})
                await send({"type": "http.response.body", "body": b"Request too large"})
                return
            if not event.get("more_body"):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
