"""Week 4 acceptance for file_read / file_write / file_edit."""

from __future__ import annotations

from agent_anvil.events import read_events
from agent_anvil.tools.base import ToolContext
from agent_anvil.tools.file_edit import FileEditTool
from agent_anvil.tools.file_read import FileReadTool
from agent_anvil.tools.file_write import FileWriteTool


def test_file_write_creates_and_emits_mutation(tool_ctx: ToolContext) -> None:
    tool = FileWriteTool(tool_ctx)
    result = tool.run({"path": "hello.txt", "content": "hi\n"})
    assert result.exit_code == 0
    assert (tool_ctx.workspace / "hello.txt").read_text() == "hi\n"

    tool_ctx.events.close()
    events = read_events(tool_ctx.events.path)
    muts = [e for e in events if e.type == "file_mutation"]
    assert len(muts) == 1
    assert muts[0].data["path"] == "hello.txt"
    assert muts[0].data["operation"] == "create"
    assert muts[0].data["size_before"] == 0
    assert muts[0].data["size_after"] == 3


def test_file_write_overwrite_marks_edit(tool_ctx: ToolContext) -> None:
    target = tool_ctx.workspace / "x.txt"
    target.write_text("old")
    tool = FileWriteTool(tool_ctx)
    tool.run({"path": "x.txt", "content": "new"})
    tool_ctx.events.close()
    events = read_events(tool_ctx.events.path)
    muts = [e for e in events if e.type == "file_mutation"]
    assert muts[0].data["operation"] == "edit"
    assert muts[0].data["size_before"] == 3


def test_file_write_rejects_path_escape(tool_ctx: ToolContext) -> None:
    tool = FileWriteTool(tool_ctx)
    result = tool.run({"path": "../escaped.txt", "content": "x"})
    assert result.is_error is True


def test_file_read_returns_line_numbered_content(tool_ctx: ToolContext) -> None:
    (tool_ctx.workspace / "a.py").write_text("line one\nline two\nline three\n")
    tool = FileReadTool(tool_ctx)
    result = tool.run({"path": "a.py"})
    assert result.exit_code == 0
    assert "1: line one" in result.content
    assert "3: line three" in result.content


def test_file_read_range(tool_ctx: ToolContext) -> None:
    (tool_ctx.workspace / "a.py").write_text("a\nb\nc\nd\ne\n")
    tool = FileReadTool(tool_ctx)
    result = tool.run({"path": "a.py", "start_line": 2, "end_line": 4})
    assert "2: b" in result.content
    assert "4: d" in result.content
    assert "1: a" not in result.content
    assert "5: e" not in result.content


def test_file_read_not_found(tool_ctx: ToolContext) -> None:
    tool = FileReadTool(tool_ctx)
    result = tool.run({"path": "nope.txt"})
    assert result.is_error is True


def test_file_edit_replaces_single_line(tool_ctx: ToolContext) -> None:
    (tool_ctx.workspace / "f.py").write_text("a\nb\nc\n")
    tool = FileEditTool(tool_ctx)
    result = tool.run({"path": "f.py", "start_line": 2, "end_line": 2, "new_content": "B"})
    assert result.exit_code == 0
    assert (tool_ctx.workspace / "f.py").read_text() == "a\nB\nc\n"


def test_file_edit_replaces_range(tool_ctx: ToolContext) -> None:
    (tool_ctx.workspace / "f.py").write_text("a\nb\nc\nd\n")
    tool = FileEditTool(tool_ctx)
    result = tool.run({"path": "f.py", "start_line": 2, "end_line": 3, "new_content": "X\nY\nZ"})
    assert result.exit_code == 0
    assert (tool_ctx.workspace / "f.py").read_text() == "a\nX\nY\nZ\nd\n"


def test_file_edit_delete_range(tool_ctx: ToolContext) -> None:
    (tool_ctx.workspace / "f.py").write_text("a\nb\nc\nd\n")
    tool = FileEditTool(tool_ctx)
    result = tool.run({"path": "f.py", "start_line": 2, "end_line": 3, "new_content": ""})
    assert result.exit_code == 0
    assert (tool_ctx.workspace / "f.py").read_text() == "a\nd\n"


def test_file_edit_append_past_eof(tool_ctx: ToolContext) -> None:
    (tool_ctx.workspace / "f.py").write_text("a\nb\nc\n")  # 3 lines
    tool = FileEditTool(tool_ctx)
    result = tool.run({"path": "f.py", "start_line": 4, "end_line": 4, "new_content": "d"})
    assert result.exit_code == 0
    assert (tool_ctx.workspace / "f.py").read_text() == "a\nb\nc\nd\n"


def test_file_edit_rejects_invalid_range(tool_ctx: ToolContext) -> None:
    (tool_ctx.workspace / "f.py").write_text("a\n")
    tool = FileEditTool(tool_ctx)
    result = tool.run({"path": "f.py", "start_line": 5, "end_line": 5, "new_content": "x"})
    assert result.is_error is True


def test_file_edit_preserves_trailing_newline_behavior(tool_ctx: ToolContext) -> None:
    # File without trailing newline stays without trailing newline.
    target = tool_ctx.workspace / "noeol.txt"
    target.write_text("a\nb")
    FileEditTool(tool_ctx).run({"path": "noeol.txt", "start_line": 2, "end_line": 2, "new_content": "B"})
    assert target.read_text() == "a\nB"
