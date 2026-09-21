"""Own subprocess lifetimes so stopping the server also stops acquisition/transcoding."""

import os
import signal
import subprocess
import threading


class Processes:
    def __init__(self):
        self.lock = threading.Lock()
        self.active: set[subprocess.Popen] = set()
        self.closed = False

    @staticmethod
    def terminate(process):
        if process.poll() is None:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass

    def run(self, args: list[str], timeout: int, text: bool = False):
        with self.lock:
            if self.closed:
                raise RuntimeError("Server is shutting down")
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=text,
                encoding="utf-8" if text else None,
                errors="replace" if text else None,
                start_new_session=os.name == "posix",
            )
            self.active.add(process)
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.terminate(process)
                process.communicate()
                raise
            return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        finally:
            with self.lock:
                self.active.discard(process)

    def close(self):
        with self.lock:
            self.closed = True
            for process in self.active:
                self.terminate(process)
