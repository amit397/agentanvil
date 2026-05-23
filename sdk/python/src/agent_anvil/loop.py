"""Main agent loop.

One iteration ("step") = one LLM call + zero or more tool calls. The loop runs
until stop_reason is `end_turn`, max_steps is hit, or an error occurs.

Event ordering inside a step (INTERFACES.md §2):

    agent_step_start
    llm_call_start
    llm_call_end
    [tool_call_start, tool_call_end, file_mutation*]  zero or more times
    agent_step_end

Bracketed by `agent_start` ... `agent_done` at the task level. `agent_error`
fires from the except branch if an uncaught exception escapes; we still emit
`agent_done` with outcome=failed so consumers see a clean termination.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import LLMClient, LLMResponse, ToolUse
from .config import AgentTaskSpec
from .deterministic import Clock
from .events import EventWriter
from .pricing import compute_cost
from .tools import Tool, ToolContext, build_tools

logger = logging.getLogger(__name__)

DEFAULT_MAX_STEPS = 25


@dataclass
class LoopRuntime:
    task_id: str
    workspace: Path
    events: EventWriter
    clock: Clock
    client: LLMClient


def _canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_request(
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    params: dict[str, str],
) -> str:
    payload = {"system": system, "messages": messages, "tools": tools, "params": params}
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def _hash_response(resp: LLMResponse) -> str:
    payload = {
        "text_blocks": resp.text_blocks,
        "tool_uses": [{"id": t.id, "name": t.name, "input": t.input} for t in resp.tool_uses],
        "stop_reason": resp.stop_reason,
    }
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def _build_assistant_message(resp: LLMResponse) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for text in resp.text_blocks:
        content.append({"type": "text", "text": text})
    for tu in resp.tool_uses:
        content.append({"type": "tool_use", "id": tu.id, "name": tu.name, "input": tu.input})
    return {"role": "assistant", "content": content}


def run(spec: AgentTaskSpec, runtime: LoopRuntime) -> dict[str, Any]:
    """Run the agent loop until completion. Returns the final `agent_done.data`."""

    events = runtime.events
    clock = runtime.clock
    workspace = runtime.workspace

    def ctx_factory(timeout: int) -> ToolContext:
        return ToolContext(
            workspace=workspace,
            timeout_seconds=timeout,
            events=events,
            clock=clock,
        )

    tools: list[Tool] = build_tools(spec.tools, ctx_factory)
    tool_map: dict[str, Tool] = {t.name: t for t in tools}
    tool_schemas = [t.schema() for t in tools]

    model_provider = spec.model.provider if spec.model else ""
    model_name = spec.model.name if spec.model else ""
    params = spec.model.params if spec.model else {}

    max_steps = spec.max_steps if spec.max_steps is not None else DEFAULT_MAX_STEPS

    events.set_step(0)
    events.emit(
        "agent_start",
        {
            "task_id": runtime.task_id,
            "prompt": spec.prompt,
            "model": {"provider": model_provider, "name": model_name},
            "tools": [s["name"] for s in tool_schemas],
            "max_steps": max_steps,
        },
    )

    system_prompt = spec.system_prompt
    messages: list[dict[str, Any]] = [{"role": "user", "content": spec.prompt}]

    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    step = 0
    outcome = "completed"
    wall_start = time.time()

    try:
        while step < max_steps:
            events.set_step(step)
            events.emit("agent_step_start", {"step": step})

            request_hash = _hash_request(system_prompt, messages, tool_schemas, params)
            events.emit(
                "llm_call_start",
                {
                    "provider": model_provider,
                    "model": model_name,
                    "request_hash": request_hash,
                    "messages_count": len(messages),
                    "params": params,
                },
            )

            t_llm_start_ns = clock.monotonic_ns()
            resp = runtime.client.complete(
                system=system_prompt,
                messages=messages,
                tools=tool_schemas,
                params=params,
            )
            t_llm_end_ns = clock.monotonic_ns()

            cost = compute_cost(model_name, resp.input_tokens, resp.output_tokens)
            total_input_tokens += resp.input_tokens
            total_output_tokens += resp.output_tokens
            total_cost += cost

            events.emit(
                "llm_call_end",
                {
                    "request_hash": request_hash,
                    "response_hash": _hash_response(resp),
                    "input_tokens": resp.input_tokens,
                    "output_tokens": resp.output_tokens,
                    "stop_reason": resp.stop_reason,
                    "cost_usd": round(cost, 6),
                    "latency_ms": max((t_llm_end_ns - t_llm_start_ns) // 1_000_000, 0),
                },
            )

            messages.append(_build_assistant_message(resp))

            if resp.stop_reason == "tool_use" and resp.tool_uses:
                tool_results: list[dict[str, Any]] = []
                for tu in resp.tool_uses:
                    tool_results.append(_run_one_tool(tu, tool_map, events, clock))
                messages.append({"role": "user", "content": tool_results})
                events.emit("agent_step_end", {"step": step})
                step += 1
                continue

            # Either end_turn, max_tokens, stop_sequence, error, or tool_use
            # with no actual tool_uses. In all cases, we stop iterating.
            events.emit("agent_step_end", {"step": step})
            step += 1

            if resp.stop_reason == "end_turn":
                outcome = "completed"
            elif resp.stop_reason == "max_tokens":
                outcome = "failed"
            elif resp.stop_reason == "error":
                outcome = "failed"
            else:
                outcome = "completed"
            break
        else:
            outcome = "max_steps"

    except Exception as exc:
        logger.exception("Agent loop crashed")
        events.emit("agent_error", {"type": type(exc).__name__, "message": str(exc)})
        outcome = "failed"

    done_data: dict[str, Any] = {
        "outcome": outcome,
        "total_steps": step,
        "total_cost_usd": round(total_cost, 6),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "wall_clock_seconds": round(time.time() - wall_start, 3),
    }
    events.emit("agent_done", done_data)
    return done_data


def _run_one_tool(
    tu: ToolUse,
    tool_map: dict[str, Tool],
    events: EventWriter,
    clock: Clock,
) -> dict[str, Any]:
    """Execute one tool_use block, emit start/end events, return tool_result block."""
    tool = tool_map.get(tu.name)
    events.emit(
        "tool_call_start",
        {"tool_name": tu.name, "args": tu.input, "tool_call_id": tu.id},
    )
    t0 = clock.monotonic_ns()

    if tool is None:
        events.emit(
            "tool_call_end",
            {
                "tool_call_id": tu.id,
                "result": f"Tool not available: {tu.name}",
                "result_truncated": False,
                "exit_code": 127,
                "latency_ms": 0,
                "result_blob_path": None,
            },
        )
        return {
            "type": "tool_result",
            "tool_use_id": tu.id,
            "content": f"Tool not available: {tu.name}",
            "is_error": True,
        }

    try:
        result = tool.run(tu.input)
    except Exception as exc:
        logger.exception("Tool %s raised", tu.name)
        result_content = f"Tool {tu.name} raised {type(exc).__name__}: {exc}"
        events.emit(
            "tool_call_end",
            {
                "tool_call_id": tu.id,
                "result": result_content,
                "result_truncated": False,
                "exit_code": 1,
                "latency_ms": max((clock.monotonic_ns() - t0) // 1_000_000, 0),
                "result_blob_path": None,
            },
        )
        return {
            "type": "tool_result",
            "tool_use_id": tu.id,
            "content": result_content,
            "is_error": True,
        }

    t1 = clock.monotonic_ns()
    events.emit(
        "tool_call_end",
        {
            "tool_call_id": tu.id,
            "result": result.content,
            "result_truncated": result.truncated,
            "exit_code": result.exit_code,
            "latency_ms": max((t1 - t0) // 1_000_000, 0),
            "result_blob_path": None,
        },
    )
    return {
        "type": "tool_result",
        "tool_use_id": tu.id,
        "content": result.content,
        "is_error": result.is_error,
    }
