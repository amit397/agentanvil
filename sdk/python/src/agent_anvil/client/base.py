"""LLM client interface.

Provider-agnostic. The loop only depends on this shape; provider-specific
quirks (Anthropic's content blocks, OpenAI's tool_calls array) are translated
behind it.

We deliberately model Anthropic-shaped tool_use semantics here (one stop_reason,
a flat list of tool_use blocks per turn) because that's our v1 target. OpenAI
support is post-v1 (PLAN-A.md §"What to drop").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

StopReason = Literal["end_turn", "tool_use", "max_tokens", "stop_sequence", "error"]


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text_blocks: list[str] = field(default_factory=list)
    tool_uses: list[ToolUse] = field(default_factory=list)
    stop_reason: StopReason = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0
    response_id: str = ""
    raw: dict[str, Any] | None = None


class LLMClient(Protocol):
    provider: str
    model: str

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        params: dict[str, str],
    ) -> LLMResponse: ...
