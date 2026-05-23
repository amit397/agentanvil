"""Tool registry: maps tool names from the AgentTaskSpec into instances.

The registry is intentionally explicit (no auto-discovery) so the set of
available tools is grep-able. Adding a new tool means adding one line here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import Tool, ToolContext

if TYPE_CHECKING:
    from ..config import ToolSpec

logger = logging.getLogger(__name__)


def _registry() -> dict[str, type[Tool]]:
    # Imports are local so the SDK can run without optional deps installed.
    # When a tool isn't available, build_tools logs and skips it.
    from .bash import BashTool
    from .file_edit import FileEditTool
    from .file_read import FileReadTool
    from .file_write import FileWriteTool
    from .web_search import WebSearchTool

    return {
        BashTool.name: BashTool,
        FileReadTool.name: FileReadTool,
        FileWriteTool.name: FileWriteTool,
        FileEditTool.name: FileEditTool,
        WebSearchTool.name: WebSearchTool,
    }


def list_available() -> list[str]:
    return sorted(_registry().keys())


def build_tools(
    specs: list[ToolSpec], ctx_factory: object
) -> list[Tool]:
    """Instantiate the tools requested by the AgentTaskSpec.

    `ctx_factory(timeout_seconds: int) -> ToolContext` is called once per tool
    with the per-tool timeout, so each tool gets its own context with the
    right timeout but shares the EventWriter and workspace.
    """
    registry = _registry()
    tools: list[Tool] = []
    for spec in specs:
        cls = registry.get(spec.name)
        if cls is None:
            logger.warning("Unknown tool %r in AgentTaskSpec; skipping", spec.name)
            continue
        timeout = spec.timeout_seconds if spec.timeout_seconds is not None else 60
        ctx: ToolContext = ctx_factory(timeout)  # type: ignore[operator]
        tools.append(cls(ctx))
    return tools
