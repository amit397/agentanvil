"""Week 4 acceptance: Clock + RNG record and replay identically."""

from __future__ import annotations

import pytest

from agent_anvil.deterministic import (
    ReplayClock,
    ReplayRNG,
    SystemClock,
    SystemRNG,
)


def test_system_clock_now_iso_format() -> None:
    iso = SystemClock().now_iso()
    # Shape: 2026-05-22T14:30:00.123Z
    assert iso.endswith("Z")
    assert len(iso) == len("2026-05-22T14:30:00.123Z")


def test_system_clock_monotonic_is_monotonic() -> None:
    c = SystemClock()
    a = c.monotonic_ns()
    b = c.monotonic_ns()
    assert b >= a


def test_replay_clock_yields_recorded_pairs() -> None:
    recorded = [
        ("2026-01-15T10:30:00.123Z", 1_000),
        ("2026-01-15T10:30:00.456Z", 2_000),
    ]
    clock = ReplayClock(recorded)
    # First event uses pair 0.
    assert clock.now_iso() == recorded[0][0]
    assert clock.monotonic_ns() == recorded[0][1]
    clock.tick()
    assert clock.now_iso() == recorded[1][0]
    assert clock.monotonic_ns() == recorded[1][1]


def test_system_rng_seedable() -> None:
    a = SystemRNG(seed=42)
    b = SystemRNG(seed=42)
    assert a.random() == b.random()
    assert a.randint(0, 100) == b.randint(0, 100)


def test_replay_rng_yields_recorded_values() -> None:
    rng = ReplayRNG([0.5, 0.25, 7])
    assert rng.random() == 0.5
    assert rng.random() == 0.25
    assert rng.randint(0, 10) == 7


def test_replay_rng_raises_when_exhausted() -> None:
    rng = ReplayRNG([0.1])
    rng.random()
    with pytest.raises(RuntimeError):
        rng.random()
