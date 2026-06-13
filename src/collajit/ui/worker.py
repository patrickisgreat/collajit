"""Run blocking work (ingest, generation) off the UI thread.

A tiny QRunnable wrapper that calls a function and reports result / error /
progress back to the GUI thread via signals. Pass a ``progress`` keyword only if
the target accepts one — :func:`run_async` injects it when ``with_progress`` is set.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Signals(QObject):
    finished = Signal(object)  # result
    error = Signal(str)
    progress = Signal(int, int)  # done, total


class _Task(QRunnable):
    def __init__(self, fn: Callable[..., Any], args, kwargs, with_progress: bool):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = dict(kwargs)
        self.with_progress = with_progress
        self.signals = _Signals()

    @Slot()
    def run(self) -> None:
        try:
            if self.with_progress:
                self.kwargs["progress"] = lambda done, total: self.signals.progress.emit(
                    int(done), int(total)
                )
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # surfaced to the user, never crashes the app
            self.signals.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.signals.finished.emit(result)


def run_async(
    fn: Callable[..., Any],
    *args,
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    with_progress: bool = False,
    **kwargs,
) -> None:
    """Schedule ``fn(*args, **kwargs)`` on the global thread pool."""
    task = _Task(fn, args, kwargs, with_progress)
    if on_done:
        task.signals.finished.connect(on_done)
    if on_error:
        task.signals.error.connect(on_error)
    if on_progress:
        task.signals.progress.connect(on_progress)
    QThreadPool.globalInstance().start(task)
