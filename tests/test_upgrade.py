import pathlib
import sqlite3
import sys

from retrostream.database import Database
from retrostream.main import main


def test_v1_database_migrates_without_losing_library(tmp_path):
    path = tmp_path / "existing.sqlite3"
    initial = (pathlib.Path(__file__).parents[1] / "retrostream/database/001_initial.sql").read_text()
    db = sqlite3.connect(path)
    db.executescript(initial)
    db.execute(
        "INSERT INTO media(id,youtube_id,original_url,youtube_title,title,added) VALUES(?,?,?,?,?,?)",
        ("a" * 32, "abcdefghijk", "https://youtu.be/abcdefghijk", "Existing", "Existing", 1.0),
    )
    db.commit()
    db.close()
    upgraded = Database(path)
    assert upgraded.one("PRAGMA user_version")["user_version"] == 4
    assert upgraded.one("SELECT title FROM media")["title"] == "Existing"
    assert upgraded.one("SELECT name FROM sqlite_master WHERE name='administrators'")
    assert upgraded.one("SELECT name FROM sqlite_master WHERE name='cache_preferences'")
    assert upgraded.one("SELECT profile_version FROM cache_entries LIMIT 1") is None
    columns = upgraded.all("PRAGMA table_info(cache_entries)")
    assert next(column for column in columns if column["name"] == "profile_version")["dflt_value"] == "1"


def test_init_db_migrates_without_issuing_throwaway_setup_code(tmp_path, monkeypatch, caplog):
    data = tmp_path / "data"
    monkeypatch.setenv("RETROSTREAM_DATA_DIR", str(data))
    monkeypatch.setattr(sys, "argv", ["retrostream", "--init-db"])

    main()

    database = Database(data / "retrostream.sqlite3")
    assert database.one("PRAGMA user_version")["user_version"] == 4
    assert not database.one("SELECT 1 FROM settings WHERE key='setup_token_hash'")
    assert "Setup code" not in caplog.text
