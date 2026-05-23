"""Event schema + JSONL writer.

Matches INTERFACES.md §2 exactly. Each event has the envelope:

    {"schema": "agent-anvil/v1", "task_id": ..., "step": N, "ts": ISO8601,
     "monotonic_ns": int, "type": <type>, "data": {...}}

The JSONL writer flushes after every event so that crashes don't lose the
trailing events. This is non-negotiable: the trace is the source of truth
for replay, and a partial trace is more useful than no trace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .deterministic import Clock, SystemClock

SCHEMA = "agent-anvil/v1"

EventType = Literal[
    "agent_start",
    "agent_step_start",
    "llm_call_start",
    "llm_call_end",
    "tool_call_start",
    "tool_call_end",
    "file_mutation",
    "network_request",
    "network_response",
    "checkpoint_start",
    "checkpoint_end",
    "agent_step_end",
    "agent_done",
    "agent_error",
]

# Allowed values for agent_done.data.outcome (INTERFACES.md §2).
DoneOutcome = Literal["completed", "failed", "timeout", "max_steps", "evicted"]


class EventEnvelope(BaseModel):
    """The on-wire shape of one event.

    `schema` is a reserved name in Pydantic v2's BaseModel, so we store it as
    `schema_` internally and serialize via the alias.
    """

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=SCHEMA, alias="schema")
    task_id: str
    step: int
    ts: str
    monotonic_ns: int
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)


class EventWriter:
    """Append-only JSONL writer with flush-after-every-event semantics.

    Construct one per task. The writer tracks the current step so callers
    don't have to thread it through every emit() call — set it once at the
    start of each agent loop iteration.

    If `echo` is set, each event line is also written there. The intended use
    is to point it at sys.stdout so `kubectl logs` shows the trace when the
    pod's trace dir is an ephemeral emptyDir (the common case until Phase 2B
    ships persistent trace storage).
    """

    def __init__(
        self,
        path: Path,
        task_id: str,
        clock: Clock | None = None,
        echo: Any | None = None,
    ) -> None:
        self._path = path
        self._task_id = task_id
        self._clock: Clock = clock or SystemClock()
        self._step = 0
        self._echo = echo
        path.parent.mkdir(parents=True, exist_ok=True)
        # Line-buffered so OS buffers don't hold events back, but we still
        # explicit flush() after each write to defeat any Python-side buffering.
        self._fp = path.open("a", encoding="utf-8", buffering=1)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def task_id(self) -> str:
        return self._task_id

    def set_step(self, step: int) -> None:
        self._step = step

    def emit(self, type: EventType, data: dict[str, Any] | None = None) -> EventEnvelope:
        envelope = EventEnvelope(
            schema=SCHEMA,
            task_id=self._task_id,
            step=self._step,
            ts=self._clock.now_iso(),
            monotonic_ns=self._clock.monotonic_ns(),
            type=type,
            data=data or {},
        )
        line = envelope.model_dump_json(by_alias=True) + "\n"
        self._fp.write(line)
        self._fp.flush()
        if self._echo is not None:
            self._echo.write(line)
            self._echo.flush()
        # If the clock is a ReplayClock, advance it. SystemClock has no tick.
        tick = getattr(self._clock, "tick", None)
        if callable(tick):
            tick()
        return envelope

    def close(self) -> None:
        if not self._fp.closed:
            self._fp.close()

    def __enter__(self) -> EventWriter:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


def read_events(path: Path) -> list[EventEnvelope]:
    """Load an events.jsonl file. Mainly for tests and offline analysis."""
    events: list[EventEnvelope] = []
    with path.open(encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            events.append(EventEnvelope.model_validate(json.loads(line)))
    return events
