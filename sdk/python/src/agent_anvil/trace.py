"""Offline trace loader.

For Week 4 (event schema freeze) we only need to load `events.jsonl` and
verify it round-trips through the EventEnvelope shape. The full trace bundle
(tar.gz with manifest, snapshots, caches per INTERFACES.md §3) lands in
Phase 2A when the recording proxy goes in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .events import EventEnvelope, read_events


@dataclass
class Trace:
    """An in-memory representation of one task's trace."""

    task_id: str
    events: list[EventEnvelope] = field(default_factory=list)

    @property
    def total_steps(self) -> int:
        return max((e.step for e in self.events), default=0) + 1 if self.events else 0

    def by_type(self, event_type: str) -> list[EventEnvelope]:
        return [e for e in self.events if e.type == event_type]


def load_trace(path: Path | str) -> Trace:
    """Load a trace from either an events.jsonl path or a directory containing it."""
    p = Path(path)
    if p.is_dir():
        events_path = p / "events.jsonl"
    else:
        events_path = p
    if not events_path.is_file():
        raise FileNotFoundError(events_path)
    events = read_events(events_path)
    task_id = events[0].task_id if events else ""
    return Trace(task_id=task_id, events=events)
