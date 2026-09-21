import re

import pytest
from fastapi.testclient import TestClient

from retrostream.app import create_app
from retrostream.security import safe_return


def csrf_from(response):
    return re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)


def test_first_run_setup_login_logout_and_public_playback(service):
    playlist = service.library.create_playlist("Public playback")
    with TestClient(create_app(service=service), base_url="http://localhost") as client:
        redirect = client.get("/library", follow_redirects=False)
        assert redirect.status_code == 303
        assert redirect.headers["location"].startswith("/setup?return_to=")
        assert client.get("/api/status").status_code == 401
        assert client.get(f"/playlists/{playlist['slug']}/audio.asx").status_code == 200
        assert client.get("/media/not-an-id/audio").status_code == 404

        setup = client.get("/setup")
        stored = service.db.one("SELECT value FROM settings WHERE key='setup_token_hash'")["value"]
        assert service.auth.setup_code not in stored
        bad = client.post(
            "/setup",
            data={
                "csrf": csrf_from(setup),
                "code": "WRONG-CODE",
                "username": "admin",
                "password": "correct horse battery staple",
                "confirm_password": "correct horse battery staple",
                "return_to": "/library?q=test",
            },
            follow_redirects=False,
        )
        assert bad.status_code == 303 and "error=" in bad.headers["location"]
        assert not service.auth.has_admin()

        setup = client.get("/setup?return_to=/library%3Fq%3Dtest")
        created = client.post(
            "/setup",
            data={
                "csrf": csrf_from(setup),
                "code": service.auth.setup_code,
                "username": "admin",
                "password": "correct horse battery staple",
                "confirm_password": "correct horse battery staple",
                "return_to": "/library?q=test",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        assert created.headers["location"].startswith("/library?q=test")
        assert client.get("/library").status_code == 200
        admin = service.db.one("SELECT * FROM administrators")
        assert admin["username"] == "admin" and "correct horse" not in admin["password_hash"]
        assert not service.db.one("SELECT 1 FROM settings WHERE key='setup_token_hash'")

        csrf = client.get("/api/csrf").json()["csrf_token"]
        assert client.post("/logout", data={"csrf": csrf}, follow_redirects=False).status_code == 303
        assert client.get("/library", follow_redirects=False).headers["location"].startswith("/login")
        login = client.get("/login")
        invalid = client.post(
            "/login",
            data={
                "csrf": csrf_from(login),
                "username": "admin",
                "password": "wrong password",
                "return_to": "https://evil.example/steal",
            },
            follow_redirects=False,
        )
        assert invalid.status_code == 303 and invalid.headers["location"].startswith("/login?")
        login = client.get("/login")
        valid = client.post(
            "/login",
            data={
                "csrf": csrf_from(login),
                "username": "admin",
                "password": "correct horse battery staple",
                "return_to": "//evil.example/steal",
            },
            follow_redirects=False,
        )
        assert valid.headers["location"].startswith("/?")
        assert client.get("/api/status").status_code == 200

        password_page = client.get("/account/password")
        changed = client.post(
            "/account/password",
            data={
                "csrf": csrf_from(password_page),
                "current_password": "correct horse battery staple",
                "password": "new correct horse battery staple",
                "confirm_password": "new correct horse battery staple",
            },
            follow_redirects=False,
        )
        assert changed.status_code == 303
        assert client.get("/library").status_code == 200
        service.auth.logout(client.cookies.get("retrostream_auth"))
        with pytest.raises(ValueError):
            service.auth.login("admin", "correct horse battery staple")
        assert service.auth.login("admin", "new correct horse battery staple")


def test_safe_return_rejects_external_and_ambiguous_paths():
    for unsafe in (
        "https://evil.example/x",
        "//evil.example/x",
        "/%2f%2fevil.example/x",
        "/\\evil",
        "javascript:alert(1)",
    ):
        assert safe_return(unsafe, "/safe") == "/safe"
    assert safe_return("/library?q=rock#media-1") == "/library?q=rock#media-1"
