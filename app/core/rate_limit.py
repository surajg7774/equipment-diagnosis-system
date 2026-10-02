"""A small in-memory rate limiter (sliding window), no external services.

Why hand-rolled instead of a library: it is ~60 lines, adds no dependency to the deployment,
and takes an injectable clock so tests can "move time" instead of sleeping.

HOW IT WORKS (sliding window log)
  For each client key we remember the timestamps of its recent requests. A request is allowed if
  fewer than ``limit`` of them happened in the last ``window_seconds``; otherwise it is refused and
  we tell the client how long until its OLDEST request leaves the window. Space frees up one
  request at a time, so there is no "everything resets at :00" cliff that lets a client burst
  twice in a row.

LIMITATIONS (fine for one small instance, documented in the README)
  * State lives in this process: a restart forgets everyone, and running several instances would
    give each its own counters.
  * It protects your API quota, it is not a defence against a determined distributed attack.
"""

import logging
import math
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int  # 0 when allowed
    remaining: int  # requests left in the current window after this one


class RateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 10_000,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        # key -> timestamps of requests inside the window (oldest first). OrderedDict so that, if
        # an attacker invents endless keys, we can drop the least recently seen ones (bounded memory).
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()  # sync endpoints run in a thread pool

    @property
    def enabled(self) -> bool:
        return self.limit > 0

    def check(self, key: str) -> RateLimitDecision:
        """Record a request from ``key`` and say whether it is allowed."""
        if not self.enabled:
            return RateLimitDecision(True, 0, 0)

        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                hits = self._hits[key] = deque()
                logger.info("rate_limit_new_client", extra={"client_key": key})
            self._hits.move_to_end(key)  # most recently seen
            while hits and hits[0] <= cutoff:  # forget requests that left the window
                hits.popleft()

            if len(hits) >= self.limit:
                retry_after = max(1, math.ceil(hits[0] + self.window_seconds - now))  # round UP, never 0
                return RateLimitDecision(False, retry_after, 0)

            hits.append(now)
            if len(self._hits) > self._max_keys:
                self._evict(cutoff)
            return RateLimitDecision(True, 0, self.limit - len(hits))

    def _evict(self, cutoff: float) -> None:
        """Bound memory: drop idle clients first, then the least recently seen ones."""
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]
        while len(self._hits) > self._max_keys:
            self._hits.popitem(last=False)


def client_key(request: Request, proxy_hops: int = 0) -> str:
    """Who is making this request?

    ``proxy_hops = 0`` (default): the address of the TCP connection. Correct locally, spoof-proof.

    Behind a reverse proxy (Render) every connection comes from the proxy, so that address is the
    same for everybody. The real client appears in ``X-Forwarded-For``, but each proxy APPENDS to
    that header and the client may have sent its own value first, so only the entries on the
    RIGHT, added by infrastructure we trust, can be believed. ``proxy_hops = N`` means "the last N
    entries were added by trusted proxies": the client is the entry N positions from the right.

    Set N too LOW and clients merely share buckets (safe); too HIGH and you would read an entry the
    client wrote (spoofable). When the header has fewer entries than expected we fall back to the
    connection address rather than trust a short or forged header.
    """
    peer = request.client.host if request.client else "unknown"
    if proxy_hops <= 0:
        return peer
    entries = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    if len(entries) < proxy_hops:
        return peer
    return entries[-proxy_hops]
