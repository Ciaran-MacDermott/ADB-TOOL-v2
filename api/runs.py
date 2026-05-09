"""In-process run registry for the deck builder.

For v2 scaffold this is a simple in-memory dict — sufficient for a single
worker process. Swap for Redis/SQLite if multi-worker is required.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Literal, Optional

State = Literal["pending", "running", "done", "error", "cancelled"]


@dataclass
class Run:
    run_id:    str
    state:     State    = "pending"
    step:      str      = ""
    message:   str      = ""
    started_at: float   = field(default_factory=time.time)
    finished_at: Optional[float] = None
    artifact:  Optional[Path]    = None  # path to generated PPTX
    cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def elapsed_s(self) -> float:
        end = self.finished_at if self.finished_at else time.time()
        return end - self.started_at


_RUNS: Dict[str, Run] = {}
_LOCK = threading.Lock()


def new_run() -> Run:
    run = Run(run_id=uuid.uuid4().hex[:12])
    with _LOCK:
        _RUNS[run.run_id] = run
    return run


def get(run_id: str) -> Optional[Run]:
    return _RUNS.get(run_id)


def update(run_id: str, **fields) -> None:
    run = _RUNS.get(run_id)
    if not run:
        return
    for k, v in fields.items():
        setattr(run, k, v)
