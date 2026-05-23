"""Injectable Clock and RNG for deterministic replay.

In record mode these read from the real OS. In replay mode they read from a
recorded source so the agent observes the same time and random values it did
on the original run. The replay engine is responsible for plugging in the
recorded values; the SDK only depends on the interface.

The Clock exposes both a wall-clock (`now()`) and a monotonic counter
(`monotonic_ns()`). Per INTERFACES.md §2, `monotonic_ns` is the source of
truth for event ordering; wall-clock is informational.
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...
    def now_iso(self) -> str: ...
    def monotonic_ns(self) -> int: ...


class SystemClock:
    """Reads wall-clock and monotonic time from the OS."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def now_iso(self) -> str:
        # ISO 8601 UTC with millisecond precision and trailing Z, matching the
        # INTERFACES.md §2 example "2026-01-15T10:30:00.123Z".
        n = self.now()
        return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


class ReplayClock:
    """Yields pre-recorded (ts, monotonic_ns) pairs in order.

    Replay engine constructs this from the original events.jsonl: for each
    event the engine emits, it pops one (ts, monotonic_ns) so the replayed
    stream has identical timestamps.
    """

    def __init__(self, pairs: list[tuple[str, int]]) -> None:
        self._pairs: list[tuple[str, int]] = list(pairs)
        self._idx = 0

    def _next(self) -> tuple[str, int]:
        if self._idx >= len(self._pairs):
            raise RuntimeError("ReplayClock exhausted: more events than recorded")
        pair = self._pairs[self._idx]
        self._idx += 1
        return pair

    def now(self) -> datetime:
        iso, _ = self._pairs[self._idx]
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))

    def now_iso(self) -> str:
        # Don't advance here — events.py calls now_iso() and monotonic_ns()
        # for the same event; the writer advances explicitly via tick().
        return self._pairs[self._idx][0]

    def monotonic_ns(self) -> int:
        return self._pairs[self._idx][1]

    def tick(self) -> None:
        """Advance one event. Call after each emitted event."""
        self._next()


class RNG(Protocol):
    def random(self) -> float: ...
    def randint(self, a: int, b: int) -> int: ...


class SystemRNG:
    def __init__(self, seed: int | None = None) -> None:
        self._r = random.Random(seed)

    def random(self) -> float:
        return self._r.random()

    def randint(self, a: int, b: int) -> int:
        return self._r.randint(a, b)


class ReplayRNG:
    """Yields pre-recorded values."""

    def __init__(self, values: list[float | int]) -> None:
        self._values: list[float | int] = list(values)
        self._iter: Iterator[float | int] = iter(self._values)

    def random(self) -> float:
        try:
            return float(next(self._iter))
        except StopIteration as e:
            raise RuntimeError("ReplayRNG exhausted") from e

    def randint(self, a: int, b: int) -> int:
        try:
            return int(next(self._iter))
        except StopIteration as e:
            raise RuntimeError("ReplayRNG exhausted") from e
