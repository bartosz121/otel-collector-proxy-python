import time
from collections import defaultdict
from dataclasses import dataclass, field


def _get_time() -> float:
    return time.monotonic()


@dataclass
class RateLimitItem:
    count: int = 0
    start_time: float = field(default_factory=_get_time)


class RateLimiter:
    """
    Dollar store rate limiting, app will be deployed with 1 worker so it fine
    """

    def __init__(self, requests_limit: int, window_seconds: int) -> None:
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        self.storage: dict[str, RateLimitItem] = defaultdict(RateLimitItem)
        self._last_cleanup = time.monotonic()

    def _maybe_cleanup(self, now: float) -> None:
        if now - self._last_cleanup < 10 * self.window_seconds:
            return
        self._last_cleanup = now
        cutoff = now - 2 * self.window_seconds
        to_delete = [k for k, v in self.storage.items() if v.start_time < cutoff]
        for k in to_delete:
            del self.storage[k]

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        self._maybe_cleanup(now)
        item = self.storage[key]

        if now - item.start_time > self.window_seconds:
            item.start_time = now
            item.count = 0

        if item.count >= self.requests_limit:
            return False

        item.count += 1
        return True
