"""web_search tool: mocked stub for v1.

PLAN-A.md §"Phase 1A Build" lists web_search as "mock for now" — a real
implementation lives downstream of the recording proxy (Phase 2A). For Week
1-5 the tool exists so the registry has it, but it always returns a fixed
message so the agent doesn't loop on it.
"""

from __future__ import annotations

from typing import Any, ClassVar

from .base import Tool, ToolResult


class WebSearchTool(Tool):
    name: ClassVar[str] = "web_search"
    description: ClassVar[str] = (
        "Search the web. NOTE: this is a stub in v1 of Agent-Anvil; real "
        "results require the recording proxy (planned for Phase 2A). Avoid "
        "depending on this tool's output."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
        },
        "required": ["query"],
    }

    def _run(self, args: dict[str, Any]) -> ToolResult:
        query = args.get("query", "")
        return ToolResult(
            content=f"web_search is not implemented in v1; query was: {query!r}",
            exit_code=0,
        )
