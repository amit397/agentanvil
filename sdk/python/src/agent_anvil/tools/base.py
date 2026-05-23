"""Tool protocol and shared helpers.

Every built-in tool implements `Tool.run(args) -> ToolResult`. Tools receive a
`ToolContext` with the workspace path, timeout, and an EventWriter for
emitting `file_mutation` events when they mutate files. The loop wraps each
call in tool_call_start/tool_call_end events.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from ..deterministic import Clock
from ..events import EventWriter

# Anything larger than this gets truncated in the inline result; the full result
# is offloaded to a blob file. Matches INTERFACES.md §2 "truncated if > 64KB".
MAX_INLINE_RESULT_BYTES = 64 * 1024


class ToolResult(BaseModel):
    """The result of running one tool invocation."""

    content: str
    exit_code: int = 0
    is_error: bool = False
    truncated: bool = False


@dataclass
class ToolContext:
    workspace: Path
    timeout_seconds: int
    events: EventWriter
    clock: Clock


class Tool:
    """Base class for built-in tools.

    Subclasses set `name`, `description`, and `input_schema` as class
    attributes, and implement `_run`. The base class's `run()` clamps result
    size and is what the agent loop invokes.
    """

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    input_schema: ClassVar[dict[str, Any]] = {}

    def __init__(self, ctx: ToolContext) -> None:
        self.ctx = ctx

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def run(self, args: dict[str, Any]) -> ToolResult:
        result = self._run(args)
        if len(result.content.encode("utf-8")) > MAX_INLINE_RESULT_BYTES:
            # Truncate at byte boundary, not character — clip to 64KB then
            # decode-tolerantly. This is the inline portion only; a future
            # phase will offload the full content to a blob.
            head = result.content.encode("utf-8")[:MAX_INLINE_RESULT_BYTES]
            result.content = head.decode("utf-8", errors="replace") + "\n[truncated]"
            result.truncated = True
        return result

    def _run(self, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def emit_file_mutation(
    events: EventWriter,
    path: Path,
    workspace: Path,
    operation: str,
    size_before: int,
    size_after: int,
    contents_after: bytes,
) -> None:
    """Helper for file tools to emit a file_mutation event with consistent shape."""
    try:
        rel = str(path.relative_to(workspace))
    except ValueError:
        rel = str(path)
    events.emit(
        "file_mutation",
        {
            "path": rel,
            "operation": operation,
            "size_before": size_before,
            "size_after": size_after,
            "hash_after": sha256_bytes(contents_after) if operation != "delete" else "",
        },
    )
