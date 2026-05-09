"""In-process NPD session registry.

Wraps the result of an NPD SSO login. For the v2 scaffold the actual
Selenium login is stubbed — `connect()` just mints a token. When wiring
the real flow, call `src.acc_deck_pkg.api_extractor.sso_login()` (or
the FS variant) and stash the resulting cookies / requests.Session on
the Session object so `/api/runs` can reuse it.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# Tokens expire after this many seconds of being unused. Long enough for a
# full deck build (10–15 min in practice), short enough that a stale token
# from a forgotten browser tab doesn't sit around forever.
TTL_SECONDS = 60 * 60  # 1 hour


@dataclass
class Session:
    token:    str
    username: str
    created_at:    float = field(default_factory=time.time)
    last_seen_at:  float = field(default_factory=time.time)
    # Opaque slot for the real prod_session/cookies/jwt once wired.
    npd_handle: Optional[Any] = None

    @property
    def expires_at(self) -> float:
        return self.last_seen_at + TTL_SECONDS

    def touch(self) -> None:
        self.last_seen_at = time.time()


_SESSIONS: Dict[str, Session] = {}
_LOCK = threading.Lock()


def new_session(username: str, npd_handle: Optional[Any] = None) -> Session:
    sess = Session(
        token=secrets.token_urlsafe(24),
        username=username,
        npd_handle=npd_handle,
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
