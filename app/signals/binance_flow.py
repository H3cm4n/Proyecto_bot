from __future__ import annotations

from app.data.binance_public import DEFAULT_SYMBOLS, get_orderbook_depth, safe_float


def calculate_depth_flow(book: dict, levels: int = 20) -> dict:
    bids = book.get("bids") or []
    asks = book.get("asks") or []

    top_bids = bids[:levels]
    top_asks = asks[:levels]

    bid_notional = 0.0
    ask_notional = 0.0

    best_bid = None
    best_ask = None

    for i, row in enumerate(top_bids):
        if not isinstance(row, list) or len(row) < 2:
            continue

        price = safe_float(row[0])
        qty = safe_float(row[1])

        if price is None or qty is None:
            continue

        if i == 0:
            best_bid = price

        bid_notional += price * qty

    for i, row in enumerate(top_asks):
        if not isinstance(row, list) or len(row) < 2:
            continue

        price = safe_float(row[0])
        qty = safe_float(row[1])

        if price is None or qty is None:
            continue

        if i == 0:
            best_ask = price

        ask_notional += price * qty

    total = bid_notional + ask_notional

    if total <= 0:
        imbalance = 0.0
    else:
        imbalance = (bid_notional - ask_notional) / total

    if imbalance >= 0.15:
        flow_bias = "BULLISH"
    elif imbalance <= -0.15:
        flow_bias = "BEARISH"
    else:
        flow_bias = "NEUTRAL"

    spread = None
    spread_pct = None

    if best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid
        mid = (best_bid + best_ask) / 2

        if mid > 0:
            spread_pct = (spread / mid) * 100

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "spread_pct": spread_pct,
        "bid_notional_top": bid_notional,
        "ask_notional_top": ask_notional,
        "depth_imbalance": imbalance,
        "flow_bias": flow_bias,
        "levels": levels,
    }


def get_binance_flow_snapshot(
    symbols: list[str] | None = None,
    depth_limit: int = 100,
    levels: int = 20,
) -> list[dict]:
    symbols = symbols or DEFAULT_SYMBOLS
    rows: list[dict] = []

    for symbol in symbols:
        row = {
            "symbol": symbol,
            "status": "ERROR",
            "error": "",
        }

        try:
            book = get_orderbook_depth(symbol, limit=depth_limit)
            flow = calculate_depth_flow(book, levels=levels)

            row.update(flow)
            row["status"] = "OK"
        except Exception as exc:
            row["error"] = str(exc)

        rows.append(row)

    return rows
