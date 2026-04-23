from __future__ import annotations


PRICE_TABLE_USD_PER_MILLION = {
    # Pending operator confirmation.
    "qwen-plus": {
        "input_usd_per_million": 0.8,
        "output_usd_per_million": 2.0,
    },
}


def realized_usd(*, model: str, input_tokens: int, output_tokens: int) -> float:
    try:
        price = PRICE_TABLE_USD_PER_MILLION[model]
    except KeyError as exc:
        raise KeyError(f"no price configured for model {model!r}") from exc
    return (
        input_tokens * float(price["input_usd_per_million"])
        + output_tokens * float(price["output_usd_per_million"])
    ) / 1_000_000.0
