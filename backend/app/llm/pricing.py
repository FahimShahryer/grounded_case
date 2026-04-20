"""Approximate OpenAI token prices, USD per million tokens.

Used only for cost tracking in the `llm_calls` audit log. Update when
prices change — these are not load-bearing for correctness.
"""

from decimal import Decimal

# (input_per_1M, output_per_1M)
PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4.1": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4.1-mini": (Decimal("0.15"), Decimal("0.60")),
    "gpt-4.1-nano": (Decimal("0.10"), Decimal("0.40")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "text-embedding-3-small": (Decimal("0.02"), Decimal("0.00")),
    "text-embedding-3-large": (Decimal("0.13"), Decimal("0.00")),
}


def estimate_cost(
    model: str, prompt_tokens: int | None, completion_tokens: int | None
) -> Decimal | None:
    if prompt_tokens is None and completion_tokens is None:
        return None
    inp, out = PRICES.get(model, (Decimal("0"), Decimal("0")))
    cost = Decimal("0")
    if prompt_tokens:
        cost += Decimal(prompt_tokens) * inp / Decimal("1000000")
    if completion_tokens:
        cost += Decimal(completion_tokens) * out / Decimal("1000000")
    return cost.quantize(Decimal("0.000001"))
