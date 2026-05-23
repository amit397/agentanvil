"""file_edit tool: replace a line range with new content.

Line-range based (not diff-based) per PLAN-A.md §"Phase 1A How / Week 4 / 7":
"file_edit is the trickiest — diff-based or line-range based; pick line-range
for v1, document."

Args:
- path: workspace-relative file path
- start_line: 1-indexed first line to replace (inclusive)
- end_line: 1-indexed last line to replace (inclusive)
- new_content: the replacement text (may contain any number of lines,
  including zero — to delete the range, pass an empty string).

The range is interpreted as the closed interval [start_line, end_line] of the
original file. Pass start_line == end_line == N to replace exactly line N.
Pass start_line > original line count to append at EOF (end_line should equal
original line count + 1 in that case, but the tool also accepts start_line ==
len + 1 with any end_line >= start_line).
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import Tool, ToolResult, emit_file_mutation


class FileEditTool(Tool):
    name: ClassVar[str] = "file_edit"
    description: ClassVar[str] = (
        "Replace lines in a file with new content. Line numbers are 1-indexed "
        "and the range is inclusive on both ends. Pass new_content='' to delete "
        "the range. Append to EOF by setting start_line to (current line count + 1)."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "start_line": {
                "type": "integer",
                "minimum": 1,
                "description": "1-indexed first line to replace (inclusive).",
            },
            "end_line": {
                "type": "integer",
                "minimum": 1,
                "description": "1-indexed last line to replace (inclusive).",
            },
            "new_content": {
                "type": "string",
                "description": "Replacement text. May be empty to delete the range.",
            },
        },
        "required": ["path", "start_line", "end_line", "new_content"],
    }

    def _run(self, args: dict[str, Any]) -> ToolResult:
        path_arg = args.get("path")
        start = args.get("start_line")
        end = args.get("end_line")
        new_content = args.get("new_content")

        if not isinstance(path_arg, str) or not path_arg:
            return ToolResult(content="file_edit: missing 'path'", exit_code=2, is_error=True)
        if not isinstance(start, int) or not isinstance(end, int):
            return ToolResult(
                content="file_edit: start_line / end_line must be integers",
                exit_code=2,
                is_error=True,
            )
        if not isinstance(new_content, str):
            return ToolResult(
                content="file_edit: 'new_content' must be a string",
                exit_code=2,
                is_error=True,
            )
        if start < 1 or end < start:
            return ToolResult(
                content=f"file_edit: invalid range start_line={start} end_line={end}",
                exit_code=2,
                is_error=True,
            )

        target = (self.ctx.workspace / path_arg).resolve()
        try:
            target.relative_to(self.ctx.workspace.resolve())
        except ValueError:
            return ToolResult(
                content=f"file_edit: path escapes workspace: {path_arg}",
                exit_code=2,
                is_error=True,
            )
        if not target.exists():
            return ToolResult(
                content=f"file_edit: not found: {path_arg}",
                exit_code=2,
                is_error=True,
            )

        original_bytes = target.read_bytes()
        size_before = len(original_bytes)
        try:
            original_text = original_bytes.decode("utf-8")
        except UnicodeDecodeError as e:
            return ToolResult(
                content=f"file_edit: not utf-8 decodable: {e}",
                exit_code=2,
                is_error=True,
            )

        original_lines = original_text.split("\n")
        # `split("\n")` preserves a trailing empty element if the file ends in \n.
        # We keep the original eol-on-eof semantics by remembering whether the
        # file ended with a newline.
        ended_with_newline = original_text.endswith("\n")
        if ended_with_newline:
            # Drop the trailing empty sentinel so line counts match the
            # human-visible 1-indexed line count.
            content_lines = original_lines[:-1]
        else:
            content_lines = original_lines

        n = len(content_lines)
        # Allow appending past the end: start == n + 1 is "append after EOF".
        if start > n + 1:
            return ToolResult(
                content=(
                    f"file_edit: start_line {start} is past EOF (file has {n} lines). "
                    f"To append, use start_line={n + 1}."
                ),
                exit_code=2,
                is_error=True,
            )
        if start > n:
            # Pure append. End_line is ignored for append, but reject if it
            # doesn't make sense.
            if end < start:
                return ToolResult(
                    content=f"file_edit: end_line {end} < start_line {start}",
                    exit_code=2,
                    is_error=True,
                )
            new_lines_split = new_content.split("\n") if new_content else []
            edited = content_lines + new_lines_split
        else:
            end_clamped = min(end, n)
            new_lines_split = new_content.split("\n") if new_content else []
            edited = content_lines[: start - 1] + new_lines_split + content_lines[end_clamped:]

        new_text = "\n".join(edited)
        if ended_with_newline and not new_text.endswith("\n"):
            new_text += "\n"
        encoded = new_text.encode("utf-8")
        target.write_bytes(encoded)

        emit_file_mutation(
            self.ctx.events,
            target,
            self.ctx.workspace,
            "edit",
            size_before,
            len(encoded),
            encoded,
        )
        return ToolResult(
            content=(
                f"file_edit: replaced lines {start}-{min(end, n) if start <= n else end} "
                f"({size_before} -> {len(encoded)} bytes)"
            ),
            exit_code=0,
        )
