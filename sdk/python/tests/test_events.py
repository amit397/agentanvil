"""Week 4 event schema freeze (INTERFACES.md §2)."""

from __future__ import annotations

import json
from pathlib import Path

from agent_anvil.events import SCHEMA, EventEnvelope, EventWriter, read_events


def test_envelope_serialization_uses_schema_alias(tmp_path: Path) -> None:
    env = EventEnvelope(
        schema=SCHEMA,
        task_id="t-1",
        step=0,
        ts="2026-01-15T10:30:00.123Z",
        monotonic_ns=12345,
        type="agent_start",
        data={"prompt": "hi"},
    )
    on_wire = json.loads(env.model_dump_json(by_alias=True))
    assert on_wire["schema"] == "agent-anvil/v1"
    assert "schema_" not in on_wire


def test_writer_emits_jsonl_and_flushes(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    with EventWriter(p, task_id="t-1") as writer:
        writer.emit("agent_start", {"prompt": "hi"})
        writer.set_step(1)
        writer.emit("llm_call_start", {"provider": "mock", "model": "echo"})

        # Flush-after-every-event semantics: the file is readable mid-task.
        partial = p.read_text(encoding="utf-8").strip().splitlines()
        assert len(partial) == 2

    events = read_events(p)
    assert [e.type for e in events] == ["agent_start", "llm_call_start"]
    assert events[0].step == 0
    assert events[1].step == 1
    assert events[1].data["model"] == "echo"


def test_envelope_round_trip(tmp_path: Path) -> None:
    """Schema freeze acceptance: events serialize and parse back identically."""
    sample = {
        "schema": "agent-anvil/v1",
        "task_id": "t-2",
        "step": 7,
        "ts": "2026-02-01T00:00:00.000Z",
        "monotonic_ns": 999,
        "type": "tool_call_end",
        "data": {
            "tool_call_id": "toolu_xyz",
            "result": "ok",
            "result_truncated": False,
            "exit_code": 0,
            "latency_ms": 12,
            "result_blob_path": None,
        },
    }
    env = EventEnvelope.model_validate(sample)
    again = json.loads(env.model_dump_json(by_alias=True))
    assert again == sample


def test_all_interfaces_event_types_present() -> None:
    """All event types from INTERFACES.md §2 are accepted by the Literal."""
    expected = {
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
    }
    for t in expected:
        env = EventEnvelope(
            schema=SCHEMA,
            task_id="t",
            step=0,
            ts="2026-01-01T00:00:00.000Z",
            monotonic_ns=0,
            type=t,  # type: ignore[arg-type]
        )
        assert env.type == t
