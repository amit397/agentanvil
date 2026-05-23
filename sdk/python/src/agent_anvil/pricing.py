"""LLM token pricing table.

USD per 1M tokens. Used to compute `llm_call_end.cost_usd` per INTERFACES.md §2.
Models not in the table report cost_usd = 0.0; the operator should reject
unknown providers, but the SDK falls back gracefully.

Update this table when provider prices change (PLAN-A.md §Risks).
"""

from __future__ import annotations

# (input_per_1m, output_per_1m) in USD
PRICES: dict[str, tuple[float, float]] = {
    # Anthropic — public list price as of 2026-05.
    "claude-opus-4-7": (15.00, 75.00),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (0.80, 4.00),
    # Mock for tests.
    "scripted": (0.0, 0.0),
    "echo": (0.0, 0.0),
}


def compute_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICES:
        return 0.0
    in_price, out_price = PRICES[model]
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000.0
