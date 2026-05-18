"""In-process NPD session registry.

A Session wraps the result of a successful NPD SSO login: two authenticated
``requests.Session`` objects (prod for forecast data, qa for actuals) and
the list of industries the user can build decks for. The run worker reads
these handles from the session to avoid re-logging in per build.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Tokens expire after this many seconds of being unused. Long enough for a
# full deck build (10–15 min in practice), short enough that a stale token
# from a forgotten browser tab doesn't sit around forever.
TTL_SECONDS = 60 * 60  # 1 hour


@dataclass
class Session:
    token:        str
    username:     str
    created_at:   float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    prod_session: Optional[Any]       = None   # requests.Session
    qa_session:   Optional[Any]       = None   # requests.Session
    industries:   List[Dict[str, str]] = field(default_factory=list)
    connect_logs: List[str]            = field(default_factory=list)

    @property
    def expires_at(self) -> float:
        return self.last_seen_at + TTL_SECONDS

    def touch(self) -> None:
        self.last_seen_at = time.time()


_SESSIONS: Dict[str, Session] = {}
_LOCK = threading.Lock()


def new_session(
    username:     str,
    prod_session: Optional[Any]                = None,
    qa_session:   Optional[Any]                = None,
    industries:   Optional[List[Dict[str, str]]] = None,
    connect_logs: Optional[List[str]]          = None,
) -> Session:
    sess = Session(
        token=secrets.token_urlsafe(24),
        username=username,
        prod_session=prod_session,
        qa_session=qa_session,
        industries=industries or [],
        connect_logs=connect_logs or [],
    )
    with _LOCK:
        _SESSIONS[sess.token] = sess
    return sess


def get(token: str) -> Optional[Session]:
    sess = _SESSIONS.get(token)
    if not sess:
        return None
    if time.time() > sess.expires_at:
        with _LOCK:
            _SESSIONS.pop(token, None)
        return None
    sess.touch()
    return sess


def revoke(token: str) -> None:
    with _LOCK:
        _SESSIONS.pop(token, None)
