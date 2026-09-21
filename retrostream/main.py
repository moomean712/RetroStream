import argparse
import asyncio
import json
import logging
import signal
import sys
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from .app import create_app, streaming_app
from .config import load
from .database import Database
from .service import Service


class JSONFormatter(logging.Formatter):
    def format(self, record):
        result = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        for key in (
            "media",
            "profile",
            "playlist",
            "job",
            "kind",
            "state",
            "error",
            "mode",
            "removed_bytes",
            "protocol",
            "version",
            "action",
        ):
            if hasattr(record, key):
                result[key] = getattr(record, key)
        return json.dumps(result)


@contextmanager
def instance_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "server.lock").open("a+b") as file:
        file.seek(0)
        file.write(b"0")
        file.flush()
        file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Another RetroStream process is using this data directory") from None
        try:
            yield
        finally:
            if sys.platform == "win32":
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


class Server(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        yield


async def serve(service):
    config = service.config
    apps = [(create_app(service=service, manage_lifecycle=False), config.web_port)]
    if config.streaming_port != config.web_port:
        apps.append((streaming_app(service), config.streaming_port))
    servers = [
        Server(
            uvicorn.Config(
                app,
                host=config.bind,
                port=port,
                workers=1,
                access_log=config.debug,
                server_header=False,
                timeout_graceful_shutdown=10,
                log_config=None,
            )
        )
        for app, port in apps
    ]

    def shutdown(*_):
        for server in servers:
            server.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, shutdown)
    service.start()
    try:
        await asyncio.gather(*(server.serve() for server in servers))
    finally:
        shutdown()
        service.close()


def main():
    parser = argparse.ArgumentParser(description="RetroStream native LAN media gateway")
    parser.add_argument("--config", help="TOML configuration path")
    parser.add_argument("--init-db", action="store_true", help="Migrate the database and exit")
    parser.add_argument("--check", action="store_true", help="Print dependency and storage status, then exit")
    args = parser.parse_args()
    config = load(args.config)
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logging.basicConfig(level=logging.DEBUG if config.debug else logging.INFO, handlers=[handler])
    with instance_lock(Path(config.data_dir)):
        if args.init_db:
            Database(Path(config.data_dir) / "retrostream.sqlite3")
            return
        service = Service(config)
        if args.check:
            print(json.dumps(service.status(), indent=2))
            return
        asyncio.run(serve(service))


if __name__ == "__main__":
    main()
