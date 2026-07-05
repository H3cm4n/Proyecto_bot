from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import time

import pandas as pd

from app.data.polymarket_gamma import get_active_events, extract_market_rows
from app.data.polymarket_clob import get_orderbook, summarize_orderbook
from app.signals.orderbook_signal import classify_orderbook


DATA_DIR = Path("data")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_orderbook_snapshot(
    event_limit: int = 20,
    market_limit: int = 10,
    request_delay: float = 0.25,
) -> list[dict[str, Any]]:
    """
    Lee mercados abiertos, consulta sus orderbooks y devuelve filas listas para CSV.
    Modo seguro: solo lectura.
    """
    DATA_DIR.mkdir(exist_ok=True)

    events = get_active_events(limit=event_limit)
    markets = extract_market_rows(events)

    if markets:
        markets_df = pd.DataFrame(markets)
        markets_df.to_csv(DATA_DIR / "active_markets.csv", index=False)

    snapshot_rows = []
    observed_at = now_utc()

    for market in markets[:market_limit]:
        token_ids = market.get("clob_token_ids") or []
        outcomes = market.get("outcomes") or []

        for idx, token_id in enumerate(token_ids[:2]):
            outcome_name = outcomes[idx] if idx < len(outcomes) else f"Outcome {idx + 1}"

            try:
                orderbook = get_orderbook(str(token_id))
                summary = summarize_orderbook(orderbook)
                signal = classify_orderbook(summary)

                bid_size = float(summary.get("bid_size") or 0)
                ask_size = float(summary.get("ask_size") or 0)
                top_liquidity = min(bid_size, ask_size)

                is_alert = signal in {"WATCH_TIGHT_SPREAD", "WATCH"}

                snapshot_rows.append(
                    {
                        "observed_at": observed_at,
                        "question": market.get("question", ""),
                        "outcome": outcome_name,
                        "token_id": token_id,
                        "best_bid": summary.get("best_bid"),
                        "best_ask": summary.get("best_ask"),
                        "spread": summary.get("spread"),
                        "mid_price": summary.get("mid_price"),
                        "bid_size": bid_size,
                        "ask_size": ask_size,
                        "top_liquidity": top_liquidity,
                        "last_trade_price": summary.get("last_trade_price"),
                        "signal": signal,
                        "is_alert": is_alert,
                    }
                )

                time.sleep(request_delay)

            except Exception as error:
                snapshot_rows.append(
                    {
                        "observed_at": observed_at,
                        "question": market.get("question", ""),
                        "outcome": outcome_name,
                        "token_id": token_id,
                        "best_bid": None,
                        "best_ask": None,
                        "spread": None,
                        "mid_price": None,
                        "bid_size": None,
                        "ask_size": None,
                        "top_liquidity": None,
                        "last_trade_price": None,
                        "signal": f"ERROR: {error}",
                        "is_alert": False,
                    }
                )

    return snapshot_rows


def save_snapshot(rows: list[dict[str, Any]], path: Path, append: bool = False) -> None:
    """
    Guarda filas en CSV.
    Si append=True, agrega al historial sin borrar datos anteriores.
    """
    path.parent.mkdir(exist_ok=True)

    df = pd.DataFrame(rows)

    if append and path.exists():
        df.to_csv(path, mode="a", header=False, index=False)
    else:
        df.to_csv(path, index=False)
