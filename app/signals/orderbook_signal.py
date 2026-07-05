from typing import Any


def classify_orderbook(summary: dict[str, Any]) -> str:
    """
    Señal inicial read-only.
    No compra, no vende. Solo clasifica calidad del mercado.
    """
    best_bid = summary.get("best_bid")
    best_ask = summary.get("best_ask")
    spread = summary.get("spread")
    bid_size = summary.get("bid_size") or 0
    ask_size = summary.get("ask_size") or 0

    if best_bid is None or best_ask is None:
        return "NO_BOOK"

    if spread is None:
        return "NO_SPREAD"

    if spread <= 0:
        return "BAD_BOOK"

    if spread > 0.10:
        return "IGNORE_WIDE_SPREAD"

    if bid_size < 10 or ask_size < 10:
        return "IGNORE_LOW_TOP_LIQUIDITY"

    if spread <= 0.03:
        return "WATCH_TIGHT_SPREAD"

    return "WATCH"
