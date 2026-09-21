"""Durable single-process queue; workers never wait on child jobs."""

import json
import logging
import threading
import time
import uuid

log = logging.getLogger(__name__)


class Jobs:
    def __init__(self, db, workers: int):
        self.db, self.workers = db, workers
        self.handlers = {}
        self.stop_event = threading.Event()
        self.wakeup = threading.Event()
        self.threads = []
        self.db.execute(
            "UPDATE jobs SET state='Failed',error='Interrupted by server restart',updated=? "
            "WHERE state IN ('Running','Queued')",
            (time.time(),),
        )

    def submit(self, kind: str, payload: dict, dedupe: str | None = None) -> str:
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if dedupe:
                row = db.execute(
                    "SELECT id FROM jobs WHERE dedupe=? AND state IN ('Queued','Running')", (dedupe,)
                ).fetchone()
                if row:
                    return row[0]
            jid = uuid.uuid4().hex
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)",
                (jid, kind, json.dumps(payload), dedupe, "Queued", time.time(), time.time(), None),
            )
        self.wakeup.set()
        return jid

    def start(self):
        for number in range(self.workers):
            thread = threading.Thread(target=self._worker, name=f"jobs-{number}", daemon=True)
            thread.start()
            self.threads.append(thread)

    def close(self):
        self.stop_event.set()
        self.wakeup.set()
        for thread in self.threads:
            thread.join(timeout=5)

    def _claim(self):
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE state='Queued' ORDER BY created,id LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET state='Running',updated=? WHERE id=?", (time.time(), row["id"]))
                return dict(row)

    def _worker(self):
        while not self.stop_event.is_set():
            job = self._claim()
            if not job:
                self.wakeup.wait(0.5)
                self.wakeup.clear()
                continue
            try:
                self.handlers[job["kind"]](**json.loads(job["payload"]))
                state, error = "Completed", None
            except Exception as exc:
                state, error = "Failed", str(exc)[:1000]
                log.warning("job_failed", extra={"job": job["id"], "kind": job["kind"], "error": error})
            self.db.execute(
                "UPDATE jobs SET state=?,error=?,updated=? WHERE id=?", (state, error, time.time(), job["id"])
            )
            log.info("job_finished", extra={"job": job["id"], "state": state})
