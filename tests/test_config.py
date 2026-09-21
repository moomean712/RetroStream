from retrostream.config import Config, load


def test_new_install_ports():
    config = Config()
    assert config.web_port == 8780
    assert config.streaming_port == 8781


def test_explicit_legacy_ports_are_preserved(tmp_path):
    path = tmp_path / "retrostream.toml"
    path.write_text("web_port = 8080\nstreaming_port = 8081\n")
    config = load(str(path))
    assert config.web_port == 8080
    assert config.streaming_port == 8081


def test_docker_environment_overrides(monkeypatch):
    values = {
        "RETROSTREAM_HOSTNAME": "192.168.1.50",
        "RETROSTREAM_WEB_PORT": "8780",
        "RETROSTREAM_STREAMING_PORT": "8781",
        "RETROSTREAM_MAX_CACHE_BYTES": "1073741824",
        "RETROSTREAM_RETENTION_DAYS": "14",
        "RETROSTREAM_DEFAULT_AUDIO": "audio-high",
        "RETROSTREAM_DEFAULT_VIDEO": "video-low",
        "RETROSTREAM_MAX_TRANSCODES": "1",
        "RETROSTREAM_MAX_STREAMS": "8",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    config = load()
    assert config.hostname == "192.168.1.50"
    assert config.web_url == "http://192.168.1.50:8780"
    assert config.stream_url == "http://192.168.1.50:8781"
    assert config.default_video == "video-low"
    assert config.max_cache_bytes == 1073741824
