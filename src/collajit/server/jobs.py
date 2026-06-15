"""A tiny in-process job manager: run blocking work off the request thread and
stream progress to the UI over Server-Sent Events.

Each long endpoint submits a callable and returns a ``job_id`` immediately. The UI
either polls ``GET /api/jobs/{id}`` or subscribes to ``GET /api/jobs/{id}/events``.
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

_SENTINEL = object()  # marks end-of-stream on a subscriber queue
_MAX_LOGS = 500


@dataclass
class Job:
    id: str
    label: str = ""
    status: str = "pending"  # pending | running | done | error
    done: int = 0
    total: int = 0
    result: dict | None = None
    error: str | None = None
    logs: list[str] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "done": self.done,
            "total": self.total,
            "result": self.result,
            "error": self.error,
            "logs": self.logs,
        }


class JobManager:
    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._subs: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        fn: Callable[..., Any],
        *args,
        label: str = "",
        with_progress: bool = False,
        with_logs: bool = False,
        **kwargs,
    ) -> str:
        job = Job(id=uuid.uuid4().hex, label=label)
        with self._lock:
            self._jobs[job.id] = job
            self._subs[job.id] = []

        def run():
            job.status = "running"
            self._publish(job.id)
            try:
                if with_progress:
                    def prog(done, total, *_):
                        job.done, job.total = int(done), int(total)
                        self._publish(job.id)

                    kwargs["progress"] = prog
                if with_logs:
                    def log(message):
                        job.logs.append(str(message))
                        del job.logs[:-_MAX_LOGS]  # cap memory
                        self._publish(job.id)

                    kwargs["log"] = log
                result = fn(*args, **kwargs)
                job.result = result if isinstance(result, dict) else {"value": result}
                job.status = "done"
            except Exception as exc:  # surfaced to the UI, never crashes the server
                job.error = f"{type(exc).__name__}: {exc}"
                job.status = "error"
            self._publish(job.id, final=True)

        threading.Thread(target=run, daemon=True).start()
        return job.id

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _publish(self, job_id: str, *, final: bool = False) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        snap = job.snapshot()
        with self._lock:
            subs = list(self._subs.get(job_id, []))
        for q in subs:
            q.put(snap)
            if final:
                q.put(_SENTINEL)

    def events(self, job_id: str) -> Iterator[str]:
        """Yield SSE ``data:`` frames for a job until it finishes."""
        job = self._jobs.get(job_id)
        if job is None:
            yield _sse({"error": "unknown job", "status": "error"})
            return
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs[job_id].append(q)
        # Emit current state immediately so late subscribers aren't left waiting.
        yield _sse(job.snapshot())
        if job.status in ("done", "error"):
            return
        try:
            while True:
                item = q.get()
                if item is _SENTINEL:
                    break
                yield _sse(item)
        finally:
            with self._lock:
                if q in self._subs.get(job_id, []):
                    self._subs[job_id].remove(q)


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"
