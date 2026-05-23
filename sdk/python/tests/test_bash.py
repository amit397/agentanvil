"""Week 3 acceptance for the bash tool."""

from __future__ import annotations

import sys

from agent_anvil.tools.base import ToolContext
from agent_anvil.tools.bash import BashTool


def test_runs_command_in_workspace(tool_ctx: ToolContext) -> None:
    # Pick a portable command — Python is on PATH in both PowerShell and bash.
    (tool_ctx.workspace / "marker.txt").write_text("hello", encoding="utf-8")
    tool = BashTool(tool_ctx)
    result = tool.run({"command": f"{sys.executable} -c \"import os; print(sorted(os.listdir('.')))\""})
    assert result.exit_code == 0
    assert "marker.txt" in result.content


def test_nonzero_exit_flagged_as_error(tool_ctx: ToolContext) -> None:
    tool = BashTool(tool_ctx)
    result = tool.run({"command": f"{sys.executable} -c \"raise SystemExit(7)\""})
    assert result.exit_code == 7
    assert result.is_error is True


def test_missing_command_rejected(tool_ctx: ToolContext) -> None:
    tool = BashTool(tool_ctx)
    result = tool.run({})
    assert result.is_error is True
    assert "missing" in result.content


def test_timeout_kills_long_command(tool_ctx: ToolContext) -> None:
    # Re-create context with a short timeout to keep the test fast.
    short_ctx = ToolContext(
        workspace=tool_ctx.workspace,
        timeout_seconds=1,
        events=tool_ctx.events,
        clock=tool_ctx.clock,
    )
    tool = BashTool(short_ctx)
    result = tool.run({"command": f"{sys.executable} -c \"import time; time.sleep(10)\""})
    assert result.exit_code == 124
    assert "timed out" in result.content.lower()


def test_stderr_is_captured(tool_ctx: ToolContext) -> None:
    tool = BashTool(tool_ctx)
    result = tool.run(
        {"command": f"{sys.executable} -c \"import sys; print('out'); print('err', file=sys.stderr)\""}
    )
    assert "out" in result.content
    assert "err" in result.content


def test_schema_shape() -> None:
    tool = BashTool(
        ToolContext(workspace=__import__("pathlib").Path("."), timeout_seconds=1, events=None, clock=None)  # type: ignore[arg-type]
    )
    schema = tool.schema()
    assert schema["name"] == "bash"
    assert "command" in schema["input_schema"]["properties"]
    assert schema["input_schema"]["required"] == ["command"]
