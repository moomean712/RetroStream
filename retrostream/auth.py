"""Single-administrator authentication and first-run bootstrap."""

import base64
import hashlib
import hmac
import logging
import re
import secrets
import time

from fastapi import HTTPException, Request

log = logging.getLogger(__name__)
PASSWORD_ITERATIONS = 600_000
SESSION_SECONDS = 7 * 86400


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(derived).decode("ascii"),
    )


def _password_ok(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt, expected = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), base64.urlsafe_b64decode(salt), int(rounds)
        )
        return hmac.compare_digest(base64.urlsafe_b64encode(derived).decode("ascii"), expected)
    except (ValueError, TypeError):
        return False


class Auth:
    def __init__(self, db, web_url: str):
        self.db = db
        self.web_url = web_url
        self.setup_code = None
        self.db.execute("DELETE FROM admin_sessions WHERE expires<?", (time.time(),))
        if not self.has_admin():
            self._issue_setup_code()

    def has_admin(self) -> bool:
        return bool(self.db.one("SELECT 1 FROM administrators WHERE id=1"))

    def _issue_setup_code(self):
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        raw = "".join(secrets.choice(alphabet) for _ in range(12))
        self.setup_code = "-".join(raw[n : n + 4] for n in range(0, 12, 4))
        with self.db.connect() as db:
            db.execute(
                "INSERT INTO settings(key,value) VALUES('setup_token_hash',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_digest(self.setup_code),),
            )
        log.warning(
            "RetroStream first-run setup required. Setup URL: %s/setup Setup code: %s",
            self.web_url,
            self.setup_code,
        )

    def create_admin(self, code: str, username: str, password: str, confirm: str) -> str:
        if self.has_admin():
            raise ValueError("Administrator setup is already complete")
        saved = self.db.one("SELECT value FROM settings WHERE key='setup_token_hash'")
        normalized = code.strip().upper()
        if not saved or not hmac.compare_digest(_digest(normalized), saved["value"]):
            raise ValueError("The setup code is incorrect or has expired")
        username = username.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username):
            raise ValueError("User name must be 3–64 letters, numbers, dots, dashes, or underscores")
        if len(password) < 10 or len(password) > 1024:
            raise ValueError("Password must be at least 10 characters")
        if password != confirm:
            raise ValueError("Passwords do not match")
        with self.db.connect() as db:
            if db.execute("SELECT 1 FROM administrators WHERE id=1").fetchone():
                raise ValueError("Administrator setup is already complete")
            db.execute(
                "INSERT INTO administrators(id,username,password_hash,created) VALUES(1,?,?,?)",
                (username, _password_hash(password), time.time()),
            )
            db.execute("DELETE FROM settings WHERE key='setup_token_hash'")
        self.setup_code = None
        return self.create_session()

    def login(self, username: str, password: str) -> str:
        admin = self.db.one("SELECT username,password_hash FROM administrators WHERE id=1")
        valid = admin and hmac.compare_digest(username.strip(), admin["username"])
        valid = bool(valid and _password_ok(password, admin["password_hash"]))
        if not valid:
            raise ValueError("The user name or password is incorrect")
        return self.create_session()

    def change_password(self, current: str, password: str, confirm: str) -> str:
        admin = self.db.one("SELECT password_hash FROM administrators WHERE id=1")
        if not admin or not _password_ok(current, admin["password_hash"]):
            raise ValueError("The current password is incorrect")
        if len(password) < 10 or len(password) > 1024:
            raise ValueError("Password must be at least 10 characters")
        if password != confirm:
            raise ValueError("Passwords do not match")
        with self.db.connect() as db:
            db.execute("UPDATE administrators SET password_hash=? WHERE id=1", (_password_hash(password),))
            db.execute("DELETE FROM admin_sessions")
        return self.create_session()

    def create_session(self) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.db.execute(
            "INSERT INTO admin_sessions(token_hash,created,expires) VALUES(?,?,?)",
            (_digest(token), now, now + SESSION_SECONDS),
        )
        return token

    def username(self, token: str | None) -> str | None:
        if not token:
            return None
        row = self.db.one(
            "SELECT a.username FROM admin_sessions s CROSS JOIN administrators a "
            "WHERE s.token_hash=? AND s.expires>? AND a.id=1",
            (_digest(token), time.time()),
        )
        return row["username"] if row else None

    def logout(self, token: str | None):
        if token:
            self.db.execute("DELETE FROM admin_sessions WHERE token_hash=?", (_digest(token),))

    def require(self, request: Request):
        username = self.username(request.cookies.get("retrostream_auth"))
        if not username:
            raise HTTPException(401, "Administrator login required")
        return username
