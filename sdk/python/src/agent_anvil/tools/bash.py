"""Bash tool: run a shell command in the workspace.

Captures stdout + stderr (interleaved into one stream), enforces a timeout
from `ToolSpec.timeoutSeconds`, and reports the exit code. Bash can mutate
arbitrary files; we don't track per-file mutations here — the explicit
file_* tools do that. Callers who want byte-level workspace diffs should
use a workspace snapshot (Phase 3A) rather than scraping bash output.
"""

from __future__ import annotations

import subprocess
from typing import Any, ClassVar

from .base import Tool, ToolResult


class BashTool(Tool):
    name: ClassVar[str] = "bash"
    description: ClassVar[str] = (
        "Run a shell command in the agent workspace. Returns combined stdout and "
        "stderr along with the exit code. Long-running commands are killed at "
        "the configured timeout."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute. Runs under /bin/sh.",
            },
        },
        "required": ["command"],
    }

    def _run(self, args: dict[str, Any]) -> ToolResult:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult(
                content="bash: missing or empty 'command' argument",
                exit_code=2,
                is_error=True,
            )

        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(self.ctx.workspace),
                capture_output=True,
                text=True,
                timeout=self.ctx.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                content=f"bash: command timed out after {self.ctx.timeout_seconds}s",
                exit_code=124,
                is_error=True,
            )
        except FileNotFoundError as e:
            return ToolResult(content=f"bash: {e}", exit_code=127, is_error=True)

        out = proc.stdout or ""
        err = proc.stderr or ""
        combined = out
        if err:
            combined = f"{out}\n[stderr]\n{err}" if out else err

        return ToolResult(
            content=combined,
            exit_code=proc.returncode,
            is_error=proc.returncode != 0,
        )
