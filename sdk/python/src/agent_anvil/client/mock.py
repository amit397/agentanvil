"""Mock LLM client for tests and offline development.

Two flavors:

1. `ScriptedClient(responses=[...])` — yields canned responses in order. The
   simplest way to drive the loop deterministically through known states.

2. `EchoClient()` — replies with a single text block echoing the last user
   message. Useful for smoke tests of the loop wiring.

Both implement the `LLMClient` protocol from `client.base`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .base import LLMResponse


class ScriptedClient:
    provider = "mock"
    model = "scripted"

    def __init__(self, responses: Iterable[LLMResponse]) -> None:
        self._responses: list[LLMResponse] = list(responses)
        self._idx = 0

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        params: dict[str, str],
    ) -> LLMResponse:
        if self._idx >= len(self._responses):
            raise RuntimeError(
                f"ScriptedClient exhausted after {self._idx} responses; "
                f"loop tried to make another LLM call"
            )
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


class EchoClient:
    provider = "mock"
    model = "echo"

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        params: dict[str, str],
    ) -> LLMResponse:
        last_user = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                last_user = content if isinstance(content, str) else str(content)
                break
        return LLMResponse(
            text_blocks=[f"echo: {last_user}"],
            stop_reason="end_turn",
            input_tokens=len(last_user.split()),
            output_tokens=len(last_user.split()) + 1,
            response_id="mock-echo",
        )
