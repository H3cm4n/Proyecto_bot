from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any
import time

import pandas as pd

from app.data.polymarket_gamma import get_active_events, extract_market_rows
from app.data.polymarket_clob import get_orderbook, summarize_orderbook
from app.signals.orderbook_signal import classify_orderbook
from app.signals.scoring import score_orderbook_row


DATA_DIR = Path("data")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()



def normalize_keyword(value: str) -> str:
    return str(value or "").strip().lower()


def market_matches_excluded_keyword(market: dict, exclude_keywords: list[str] | None = None) -> bool:
    if not exclude_keywords:
        return False

    question = str(market.get("question") or market.get("title") or "").lower()

    for keyword in exclude_keywords:
        keyword = normalize_keyword(keyword)

        if keyword and keyword in question:
            return True

    return False



def market_text_for_keywords(market: dict) -> str:
    return " ".join(
        str(market.get(key) or "")
        for key in ("question", "title", "slug")
    ).lower()


def market_matches_keyword(market: dict, keyword: str) -> bool:
    text = market_text_for_keywords(market)
    keyword = normalize_keyword(keyword)

    if not keyword:
        return False

    # Short symbols like BTC, ETH, SOL, XRP should match as words, not inside other words.
    if len(keyword) <= 3:
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None

    return keyword in text


def market_matches_included_keyword(market: dict, include_keywords: list[str] | None = None) -> bool:
    if not include_keywords:
        return True

    return any(market_matches_keyword(market, keyword) for keyword in include_keywords)


def filter_included_markets(markets: list[dict], include_keywords: list[str] | None = None) -> list[dict]:
    if not include_keywords:
        return markets

    return [m for m in markets if market_matches_included_keyword(m, include_keywords)]


def filter_excluded_markets(markets: list[dict], exclude_keywords: list[str] | None = None) -> list[dict]:
    if not exclude_keywords:
        return markets

    return [
        market for market in markets
        if not market_matches_excluded_keyword(market, exclude_keywords)
    ]

def collect_orderbook_snapshot(
    event_limit: int = 20,
    market_limit: int = 10,
    request_delay: float = 0.25,
    exclude_keywords: list[str] | None = None,
    include_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Lee mercados abiertos, consulta sus orderbooks y devuelve filas listas para CSV.
    Modo seguro: solo lectura.
    """
    DATA_DIR.mkdir(exist_ok=True)

    try:
        events = get_active_events(limit=event_limit)
    except Exception as exc:
        print(f"WARN: No se pudieron obtener eventos de Gamma API: {exc}")
        return []

    markets = extract_market_rows(events)
    markets = filter_excluded_markets(markets, exclude_keywords)
    markets = filter_included_markets(markets, include_keywords)

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

                base_row = {
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

                score_data = score_orderbook_row(base_row)
                base_row.update(score_data)

                snapshot_rows.append(base_row)

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
                        "score": 0,
                        "grade": "F",
                        "action": "IGNORE",
                        "spread_points": 0,
                        "liquidity_points": 0,
                        "price_zone_points": 0,
                        "balance_points": 0,
                    }
                )

    return snapshot_rows


def save_snapshot(rows: list[dict], path: Path, append: bool = False) -> None:
    """
    Guarda snapshots en CSV manteniendo un esquema estable.

    Antes se hacía append directo, pero cuando agregamos columnas nuevas
    como edge_score, edge_direction, etc., el CSV podía quedar con filas
    de distinto tamaño. Eso rompe pandas al leer historial.
    """
    if not rows:
        return

    path.parent.mkdir(exist_ok=True)

    new_df = pd.DataFrame(rows)

    if append and path.exists():
        try:
            existing_df = pd.read_csv(path, dtype=str, on_bad_lines="skip")
        except Exception:
            backup_path = path.with_suffix(".broken.csv")
            path.rename(backup_path)
            existing_df = pd.DataFrame()

        all_columns = list(existing_df.columns)

        for column in new_df.columns:
            if column not in all_columns:
                all_columns.append(column)

        existing_df = existing_df.reindex(columns=all_columns)
        new_df = new_df.reindex(columns=all_columns)

        output_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        output_df = new_df

    output_df.to_csv(path, index=False)

