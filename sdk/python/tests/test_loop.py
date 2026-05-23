"""Week 3 acceptance: the loop runs end-to-end with a mock LLM.

These tests exercise the full happy path:
- agent_start emitted
- one (or more) LLM call + tool_use round trip
- agent_done emitted with the right outcome

The mock client returns scripted responses so the loop is deterministic.
"""

from __future__ import annotations

from pathlib import Path

from agent_anvil.client.base import LLMResponse, ToolUse
from agent_anvil.client.mock import EchoClient, ScriptedClient
from agent_anvil.config import AgentTaskSpec, ModelSpec, ToolSpec
from agent_anvil.deterministic import SystemClock
from agent_anvil.events import EventWriter, read_events
from agent_anvil.loop import LoopRuntime, run


def _spec_with(tools: list[str], prompt: str = "do stuff") -> AgentTaskSpec:
    return AgentTaskSpec(
        prompt=prompt,
        system_prompt="You are an agent.",
        model=ModelSpec(provider="mock", name="scripted"),
        tools=[ToolSpec(name=t) for t in tools],
        max_steps=5,
    )


def test_loop_runs_through_end_turn(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    workspace = tmp_path / "ws"
    workspace.mkdir()

    client = EchoClient()
    with EventWriter(events_path, task_id="task-echo") as ew:
        runtime = LoopRuntime(
            task_id="task-echo",
            workspace=workspace,
            events=ew,
            clock=SystemClock(),
            client=client,
        )
        done = run(_spec_with(tools=[]), runtime)

    assert done["outcome"] == "completed"
    assert done["total_steps"] >= 1

    events = read_events(events_path)
    types = [e.type for e in events]
    assert types[0] == "agent_start"
    assert types[-1] == "agent_done"
    assert "llm_call_start" in types
    assert "llm_call_end" in types


def test_loop_handles_tool_use_round_trip(tmp_path: Path) -> None:
    """First LLM response calls bash; second returns end_turn."""
    events_path = tmp_path / "events.jsonl"
    workspace = tmp_path / "ws"
    workspace.mkdir()

    scripted = ScriptedClient(
        [
            LLMResponse(
                text_blocks=["I'll list the workspace."],
                tool_uses=[ToolUse(id="tu_1", name="bash", input={"command": "echo listed"})],
                stop_reason="tool_use",
                input_tokens=10,
                output_tokens=5,
                response_id="r1",
            ),
            LLMResponse(
                text_blocks=["Done."],
                stop_reason="end_turn",
                input_tokens=15,
                output_tokens=3,
                response_id="r2",
            ),
        ]
    )

    with EventWriter(events_path, task_id="task-tool") as ew:
        runtime = LoopRuntime(
            task_id="task-tool",
            workspace=workspace,
            events=ew,
            clock=SystemClock(),
            client=scripted,
        )
        done = run(_spec_with(tools=["bash"]), runtime)

    assert done["outcome"] == "completed"
    assert done["total_steps"] == 2

    events = read_events(events_path)
    types = [e.type for e in events]
    assert "tool_call_start" in types
    assert "tool_call_end" in types
    tool_end = next(e for e in events if e.type == "tool_call_end")
    assert "listed" in tool_end.data["result"]
    assert tool_end.data["exit_code"] == 0


def test_loop_max_steps_terminates(tmp_path: Path) -> None:
    """Pathological case: LLM keeps returning tool_use; loop bails at max_steps."""
    events_path = tmp_path / "events.jsonl"
    workspace = tmp_path / "ws"
    workspace.mkdir()

    forever = [
        LLMResponse(
            text_blocks=[],
            tool_uses=[ToolUse(id=f"t{i}", name="bash", input={"command": "echo x"})],
            stop_reason="tool_use",
            input_tokens=1,
            output_tokens=1,
            response_id=f"r{i}",
        )
        for i in range(10)
    ]
    scripted = ScriptedClient(forever)

    spec = _spec_with(tools=["bash"])
    spec.max_steps = 3

    with EventWriter(events_path, task_id="task-maxsteps") as ew:
        runtime = LoopRuntime(
            task_id="task-maxsteps",
            workspace=workspace,
            events=ew,
            clock=SystemClock(),
            client=scripted,
        )
        done = run(spec, runtime)

    assert done["outcome"] == "max_steps"
    assert done["total_steps"] == 3


def test_loop_unknown_tool_yields_tool_result_error(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    workspace = tmp_path / "ws"
    workspace.mkdir()

    scripted = ScriptedClient(
        [
            LLMResponse(
                text_blocks=[],
                tool_uses=[ToolUse(id="x1", name="nonexistent", input={})],
                stop_reason="tool_use",
                input_tokens=1,
                output_tokens=1,
                response_id="r1",
            ),
            LLMResponse(
                text_blocks=["giving up"],
                stop_reason="end_turn",
                input_tokens=1,
                output_tokens=1,
                response_id="r2",
            ),
        ]
    )

    with EventWriter(events_path, task_id="task-unknown") as ew:
        runtime = LoopRuntime(
            task_id="task-unknown",
            workspace=workspace,
            events=ew,
            clock=SystemClock(),
            client=scripted,
        )
        done = run(_spec_with(tools=[]), runtime)

    assert done["outcome"] == "completed"
    events = read_events(events_path)
    tool_end = next(e for e in events if e.type == "tool_call_end")
    assert tool_end.data["exit_code"] == 127


def test_loop_token_and_cost_aggregation(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    workspace = tmp_path / "ws"
    workspace.mkdir()

    spec = _spec_with(tools=[])
    spec.model = ModelSpec(provider="anthropic", name="claude-haiku-4-5")
    scripted = ScriptedClient(
        [
            LLMResponse(
                text_blocks=["hi"],
                stop_reason="end_turn",
                input_tokens=1_000_000,
                output_tokens=500_000,
                response_id="r",
            )
        ]
    )

    with EventWriter(events_path, task_id="task-cost") as ew:
        runtime = LoopRuntime(
            task_id="task-cost",
            workspace=workspace,
            events=ew,
            clock=SystemClock(),
            client=scripted,
        )
        done = run(spec, runtime)

    # claude-haiku-4-5 is (0.80, 4.00) per 1M.
    # 1M input * 0.80 + 0.5M output * 4.00 = 0.80 + 2.00 = 2.80 USD.
    assert abs(done["total_cost_usd"] - 2.80) < 0.001
    assert done["total_input_tokens"] == 1_000_000
    assert done["total_output_tokens"] == 500_000
