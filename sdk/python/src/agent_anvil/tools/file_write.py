"""file_write tool: write (create or overwrite) a file in the workspace.

Emits a `file_mutation` event with operation=create or operation=edit
depending on whether the file existed.
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import Tool, ToolResult, emit_file_mutation


class FileWriteTool(Tool):
    name: ClassVar[str] = "file_write"
    description: ClassVar[str] = (
        "Write a file in the workspace. Creates parent directories as needed. "
        "Overwrites any existing content."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "content": {"type": "string", "description": "Full file content to write."},
        },
        "required": ["path", "content"],
    }

    def _run(self, args: dict[str, Any]) -> ToolResult:
        path_arg = args.get("path")
        content = args.get("content")
        if not isinstance(path_arg, str) or not path_arg:
            return ToolResult(content="file_write: missing 'path'", exit_code=2, is_error=True)
        if not isinstance(content, str):
            return ToolResult(
                content="file_write: 'content' must be a string", exit_code=2, is_error=True
            )

        target = (self.ctx.workspace / path_arg).resolve()
        try:
            target.relative_to(self.ctx.workspace.resolve())
        except ValueError:
            return ToolResult(
                content=f"file_write: path escapes workspace: {path_arg}",
                exit_code=2,
                is_error=True,
            )

        size_before = target.stat().st_size if target.exists() else 0
        operation = "edit" if target.exists() else "create"

        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = content.encode("utf-8")
        target.write_bytes(encoded)

        emit_file_mutation(
            self.ctx.events,
            target,
            self.ctx.workspace,
            operation,
            size_before,
            len(encoded),
            encoded,
        )
        return ToolResult(
            content=f"file_write: wrote {len(encoded)} bytes to {path_arg}", exit_code=0
        )
