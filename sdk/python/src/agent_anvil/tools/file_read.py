"""file_read tool: read a file from the workspace.

Read modes:
- whole file (default)
- line range with `start_line` (1-indexed, inclusive) and optional `end_line`
  (1-indexed, inclusive). If `end_line` is omitted, reads to EOF.

Lines are returned with the 1-indexed line number prefix `"N: "` so the model
can refer to them by number when calling `file_edit`. (This mirrors how Aider
formats reads — it dramatically reduces off-by-one bugs in edits.)
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import Tool, ToolResult

MAX_FILE_BYTES = 1024 * 1024  # 1 MiB cap for an inline read


class FileReadTool(Tool):
    name: ClassVar[str] = "file_read"
    description: ClassVar[str] = (
        "Read a file from the workspace. Returns lines prefixed with their "
        "1-indexed line numbers, suitable for referencing in file_edit. "
        "Optionally read only a line range with start_line/end_line."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "start_line": {
                "type": "integer",
                "minimum": 1,
                "description": "1-indexed first line to read (inclusive). Default: 1.",
            },
            "end_line": {
                "type": "integer",
                "minimum": 1,
                "description": "1-indexed last line to read (inclusive). Default: EOF.",
            },
        },
        "required": ["path"],
    }

    def _run(self, args: dict[str, Any]) -> ToolResult:
        path_arg = args.get("path")
        if not isinstance(path_arg, str) or not path_arg:
            return ToolResult(content="file_read: missing 'path'", exit_code=2, is_error=True)

        target = (self.ctx.workspace / path_arg).resolve()
        # Block escapes from the workspace via "..".
        try:
            target.relative_to(self.ctx.workspace.resolve())
        except ValueError:
            return ToolResult(
                content=f"file_read: path escapes workspace: {path_arg}",
                exit_code=2,
                is_error=True,
            )

        if not target.exists():
            return ToolResult(
                content=f"file_read: not found: {path_arg}", exit_code=2, is_error=True
            )
        if not target.is_file():
            return ToolResult(
                content=f"file_read: not a regular file: {path_arg}",
                exit_code=2,
                is_error=True,
            )

        size = target.stat().st_size
        if size > MAX_FILE_BYTES:
            return ToolResult(
                content=f"file_read: file too large ({size} bytes, max {MAX_FILE_BYTES})",
                exit_code=2,
                is_error=True,
            )

        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            return ToolResult(
                content=f"file_read: not utf-8 decodable: {e}",
                exit_code=2,
                is_error=True,
            )

        lines = text.splitlines()
        start = args.get("start_line", 1)
        end = args.get("end_line", len(lines))
        if not isinstance(start, int) or not isinstance(end, int):
            return ToolResult(
                content="file_read: start_line / end_line must be integers",
                exit_code=2,
                is_error=True,
            )
        start = max(1, start)
        end = min(len(lines), end)
        if start > end and lines:
            return ToolResult(
                content=f"file_read: empty range start_line={start} end_line={end}",
                exit_code=2,
                is_error=True,
            )

        formatted = "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))
        return ToolResult(content=formatted, exit_code=0)
