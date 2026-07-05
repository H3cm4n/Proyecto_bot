from typing import Any
import requests


CLOB_BASE_URL = "https://clob.polymarket.com"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_orderbook(token_id: str) -> dict[str, Any]:
    """
    Obtiene el orderbook de un token específico.
    Es lectura pública: no requiere API key ni wallet.
    """
    url = f"{CLOB_BASE_URL}/book"

    params = {
        "token_id": token_id,
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()

    return response.json()


def summarize_orderbook(orderbook: dict[str, Any]) -> dict[str, Any]:
    """
    Calcula métricas básicas del orderbook:
    best bid, best ask, spread, mid price y tamaños.
    """
    bids = orderbook.get("bids") or []
    asks = orderbook.get("asks") or []

    parsed_bids = [
        {
            "price": safe_float(level.get("price")),
            "size": safe_float(level.get("size")),
        }
        for level in bids
    ]

    parsed_asks = [
        {
            "price": safe_float(level.get("price")),
            "size": safe_float(level.get("size")),
        }
        for level in asks
    ]

    best_bid_level = max(parsed_bids, key=lambda x: x["price"], default=None)
    best_ask_level = min(parsed_asks, key=lambda x: x["price"], default=None)

    best_bid = best_bid_level["price"] if best_bid_level else None
    best_ask = best_ask_level["price"] if best_ask_level else None

    bid_size = best_bid_level["size"] if best_bid_level else 0.0
    ask_size = best_ask_level["size"] if best_ask_level else 0.0

    spread = None
    mid_price = None

    if best_bid is not None and best_ask is not None:
        spread = round(best_ask - best_bid, 4)
        mid_price = round((best_bid + best_ask) / 2, 4)

    return {
        "asset_id": orderbook.get("asset_id", ""),
        "market": orderbook.get("market", ""),
        "timestamp": orderbook.get("timestamp", ""),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "spread": spread,
        "mid_price": mid_price,
        "last_trade_price": safe_float(orderbook.get("last_trade_price")),
        "min_order_size": safe_float(orderbook.get("min_order_size")),
        "tick_size": safe_float(orderbook.get("tick_size")),
    }
