"""In-process run registry for the deck builder.

Each deck build gets a Run record that the worker thread mutates as it
progresses. The HTTP layer reads a consistent snapshot via ``snapshot``
so concurrent pollers never see torn state.

Concurrency model
─────────────────
Concurrent runs are capped by ``RUN_SLOTS`` (a BoundedSemaphore). Worker
threads acquire a slot before flipping state to "running"; everyone
beyond the cap sits at state="queued" with ``queue_position`` and
``eta_seconds`` projected from the rolling median of recent run
durations, so colleagues hitting the server at the same time see useful
feedback instead of a frozen spinner.

The cap defaults to 3, which is comfortable on a 2-vCPU HF Space
(Chromium for NPD SSO is the dominant resource per run). Override with
the ``ADB_MAX_RUN_SLOTS`` env var.

Eviction
────────
Idle runs (state ∉ _ACTIVE_STATES) are reaped after ``TTL_SECONDS`` of
inactivity by both inline registry calls and a background reaper
thread. Worker progress and any API touch refresh ``last_touched``, so
a long deck build that's actively polled stays alive but a tab the
user closed gets cleaned up.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Literal, Optional


State = Literal["queued", "running", "done", "error", "cancelled"]

# Hard cap on per-run log lines kept in memory. Beyond this we drop the
# oldest lines so a chatty pipeline can't blow up RAM.
LOG_BUFFER_MAX = 1000


MAX_RUN_SLOTS = max(1, int(os.environ.get("ADB_MAX_RUN_SLOTS", "3")))
RUN_SLOTS = threading.BoundedSemaphore(MAX_RUN_SLOTS)

TTL_SECONDS = 60 * 60

_ACTIVE_STATES: frozenset[str] = frozenset({"queued", "running"})
_RUNNING_STATES: frozenset[str] = frozenset({"running"})
_TERMINAL_STATES: frozenset[str] = frozenset({"done", "error", "cancelled"})


# Rolling window of recent successful run durations (seconds). Drives
# the ETA shown to queued users. Bounded so a single old slow run can't
# skew the median forever.
_RECENT_DURATIONS: deque[float] = deque(maxlen=20)
_DURATIONS_LOCK = threading.Lock()


def record_run_duration(seconds: float) -> None:
    with _DURATIONS_LOCK:
        _RECENT_DURATIONS.append(seconds)


def median_run_duration() -> Optional[float]:
    with _DURATIONS_LOCK:
        d = list(_RECENT_DURATIONS)
    if not d:
        return None
    d.sort()
    mid = len(d) // 2
    return d[mid] if len(d) % 2 else (d[mid - 1] + d[mid]) / 2


@dataclass
class Run:
    run_id:       str
    state:        State = "queued"
    step:         str = ""
    message:      str = ""
    started_at:   float = field(default_factory=time.time)
    finished_at:  Optional[float] = None
    # Refreshed by worker progress (``set_state``) and by any API read
    # (``registry.get``). Eviction is keyed on this.
    last_touched: float = field(default_factory=time.time)
    artifact:     Optional[Path] = None
    artifact_xlsx: Optional[Path] = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock:         threading.Lock = field(default_factory=threading.Lock)
    logs:         list[str]      = field(default_factory=list)

    @property
    def elapsed_s(self) -> float:
        end = self.finished_at if self.finished_at else time.time()
        return end - self.started_at


_RUNS: Dict[str, Run] = {}
_MU = threading.Lock()


def new_run() -> Run:
    with _MU:
        _evict_expired_locked()
        run = Run(run_id=uuid.uuid4().hex[:12])
        _RUNS[run.run_id] = run
    return run


def get(run_id: str) -> Optional[Run]:
    with _MU:
        _evict_expired_locked()
        run = _RUNS.get(run_id)
    if run is not None:
        with run.lock:
            run.last_touched = time.time()
    return run


def list_all() -> list[Run]:
    with _MU:
        _evict_expired_locked()
        return list(_RUNS.values())


def evict_expired() -> None:
    with _MU:
        _evict_expired_locked()


def _evict_expired_locked() -> None:
    now = time.time()
    expired = [
        rid for rid, r in _RUNS.items()
        if r.state not in _ACTIVE_STATES
        and (now - r.last_touched) > TTL_SECONDS
    ]
    for rid in expired:
        _RUNS.pop(rid, None)


def set_state(
    run: Run,
    *,
    state:   Optional[State] = None,
    step:    Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    """Worker-side state mutation. Touches ``last_touched`` so an
    actively-progressing run can never be reaped mid-build."""
    with run.lock:
        run.last_touched = time.time()
        if state is not None:
            run.state = state
            if state in _TERMINAL_STATES and run.finished_at is None:
                run.finished_at = time.time()
        if step is not None:
            run.step = step
        if message is not None:
            run.message = message


def _compute_queue_info(run: Run) -> tuple[Optional[int], Optional[int], Optional[float]]:
    """Project (position, depth, eta_seconds) for ``run``.

    Returns (None, None, None) once the run is no longer queued so the
    UI hides the chip.
    """
    if run.state != "queued":
        return None, None, None

    all_runs = list_all()
    queued_sorted = sorted(
        (r for r in all_runs if r.state == "queued"),
        key=lambda r: r.started_at,
    )
    running_count = sum(1 for r in all_runs if r.state in _RUNNING_STATES)

    try:
        position = queued_sorted.index(run)
    except ValueError:
        position = 0
    depth = len(queued_sorted)

    # With MAX_RUN_SLOTS independent runs going, on average one slot
    # frees up every (median / MAX_RUN_SLOTS) seconds. Only project an
    # ETA once all slots are full — otherwise being "queued" is a
    # transient state the worker is about to leave.
    median = median_run_duration()
    if median and running_count >= MAX_RUN_SLOTS:
        eta_seconds: Optional[float] = (position + 1) * median / MAX_RUN_SLOTS
    else:
        eta_seconds = None
    return position, depth, eta_seconds


def snapshot(run: Run, *, max_log_lines: int = 200) -> dict[str, Any]:
    """Read a consistent status snapshot for the HTTP layer."""
    queue_position, queue_depth, eta_seconds = _compute_queue_info(run)
    with run.lock:
        return {
            "run_id":         run.run_id,
            "state":          run.state,
            "step":           run.step or None,
            "message":        run.message or None,
            "elapsed_s":      (run.finished_at or time.time()) - run.started_at,
            "queue_position": queue_position,
            "queue_depth":    queue_depth,
            "eta_seconds":    eta_seconds,
            "logs":           list(run.logs[-max_log_lines:]),
        }


# ── Live log capture ──────────────────────────────────────────────────
# Pipelines log progress via plain ``print()`` calls. We want those lines
# surfaced to the frontend without rewriting the pipeline. The pattern:
#
#   1. Replace ``sys.stdout`` once at startup with ``_StdoutTee`` — a thin
#      wrapper that writes through to the original stdout AND, if a Run
#      is registered for the calling thread, appends to ``run.logs``.
#   2. Each worker calls ``set_run_for_thread(run)`` before invoking the
#      pipeline and ``clear_run_for_thread()`` on exit.
#   3. Threads with no registered run (e.g. uvicorn workers, FastAPI
#      handlers) just see normal stdout behaviour.
#
# Two concurrent workers can write to two different run buffers because
# the routing target lives in ``threading.local()``.

_thread_local = threading.local()


def append_log(run: Run, line: str) -> None:
    with run.lock:
        run.logs.append(line)
        if len(run.logs) > LOG_BUFFER_MAX:
            del run.logs[: len(run.logs) - LOG_BUFFER_MAX]
        run.last_touched = time.time()


def set_run_for_thread(run: Run) -> None:
    _thread_local.run = run


def clear_run_for_thread() -> None:
    _thread_local.run = None


class _StdoutTee:
    """Tee stdout writes through to the original stream and (if any) the
    Run registered on the current thread. Thread-safe by virtue of using
    threading.local for routing."""

    def __init__(self, original):
        self._original = original

    def write(self, text: str):
        try:
            self._original.write(text)
        except Exception:
            pass
        run = getattr(_thread_local, "run", None)
        if run is None or not text:
            return
        # Split on newlines so each log line is one entry. Drop empties.
        for line in text.rstrip("\n").split("\n"):
            if line.strip():
                append_log(run, line)

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass

    # Some libraries (e.g. tqdm) probe for these:
    def isatty(self) -> bool:
        return False

    def fileno(self):
        return self._original.fileno()


_TEE_INSTALLED = False
_TEE_LOCK = threading.Lock()


def install_stdout_tee() -> None:
    """Install the tee on sys.stdout. Idempotent and safe to call
    multiple times (e.g. uvicorn's --reload re-imports the module)."""
    global _TEE_INSTALLED
    with _TEE_LOCK:
        if _TEE_INSTALLED:
            return
        if not isinstance(sys.stdout, _StdoutTee):
            sys.stdout = _StdoutTee(sys.stdout)
        _TEE_INSTALLED = True


def _reap_loop() -> None:
    """Background reaper. Without this, eviction only fires on incoming
    requests, so a deck whose tab was closed (no more polls) lives
    forever."""
    while True:
        time.sleep(60)
        try:
            evict_expired()
        except Exception:
            # Reaper must never die.
            pass


threading.Thread(target=_reap_loop, name="adb-run-reaper", daemon=True).start()
