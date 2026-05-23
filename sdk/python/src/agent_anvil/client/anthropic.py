"""Anthropic client.

Wraps `anthropic.Anthropic.messages.create` and translates the response into
our provider-neutral `LLMResponse`. Non-streaming for v1 — streaming SSE is
deferred to Phase 2A when the recording proxy needs to intercept it. The
loop itself doesn't observe streaming, only the final response.

The HTTPS_PROXY env var is honored by the `httpx` client that the Anthropic
SDK uses internally, so when the pod's HTTPS_PROXY points at the recording
proxy sidecar (INTERFACES.md §4) all traffic flows through it automatically.
"""

from __future__ import annotations

import os
from typing import Any

from .base import LLMResponse, ToolUse


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, model: str, api_key: str | None = None) -> None:
        # Import locally so the SDK can be imported without the anthropic
        # package being installed at the time the import graph is walked —
        # useful in unit tests that only exercise the mock client.
        from anthropic import Anthropic

        self.model = model
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "No Anthropic API key. Set ANTHROPIC_API_KEY or pass api_key= "
                "or set AGENT_ANVIL_API_KEY_FILE to a file containing the key."
            )
        self._client = Anthropic(api_key=key)

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        params: dict[str, str],
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": int(params.get("maxTokens") or params.get("max_tokens") or "4096"),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        temp = params.get("temperature")
        if temp is not None:
            kwargs["temperature"] = float(temp)

        msg = self._client.messages.create(**kwargs)

        text_blocks: list[str] = []
        tool_uses: list[ToolUse] = []
        for block in msg.content:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                text_blocks.append(getattr(block, "text", ""))
            elif block_type == "tool_use":
                tool_uses.append(
                    ToolUse(
                        id=getattr(block, "id", ""),
                        name=getattr(block, "name", ""),
                        input=dict(getattr(block, "input", {})),
                    )
                )

        usage = getattr(msg, "usage", None)
        in_tok = getattr(usage, "input_tokens", 0) if usage else 0
        out_tok = getattr(usage, "output_tokens", 0) if usage else 0

        stop = getattr(msg, "stop_reason", "end_turn") or "end_turn"
        # Anthropic uses the same vocabulary we declared for StopReason, modulo
        # the case where stop_reason is None (treat as end_turn).
        return LLMResponse(
            text_blocks=text_blocks,
            tool_uses=tool_uses,
            stop_reason=stop,  # type: ignore[arg-type]
            input_tokens=in_tok,
            output_tokens=out_tok,
            response_id=getattr(msg, "id", ""),
        )
