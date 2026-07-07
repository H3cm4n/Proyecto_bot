from pathlib import Path
from typing import Any

import pandas as pd

from app.data.polymarket_clob import get_orderbook, summarize_orderbook


DATA_DIR = Path("data")
PAPER_TRADES_PATH = DATA_DIR / "paper_trades.csv"


def load_paper_trades() -> pd.DataFrame:
    if not PAPER_TRADES_PATH.exists():
        return pd.DataFrame()

    return pd.read_csv(PAPER_TRADES_PATH)


def get_open_paper_trades() -> pd.DataFrame:
    df = load_paper_trades()

    if df.empty:
        return df

    if "status" not in df.columns:
        return pd.DataFrame()

    return df[df["status"] == "OPEN"].copy()


def mark_trade_to_market(trade: dict[str, Any]) -> dict[str, Any]:
    token_id = str(trade.get("token_id", ""))

    orderbook = get_orderbook(token_id)
    summary = summarize_orderbook(orderbook)

    entry_price = float(trade.get("entry_price") or 0)
    shares = float(trade.get("shares") or 0)
    notional_usdc = float(trade.get("notional_usdc") or 0)

    current_bid = float(summary.get("best_bid") or 0)
    current_ask = float(summary.get("best_ask") or 0)
    mid_price = float(summary.get("mid_price") or 0)

    conservative_exit_value = round(shares * current_bid, 4)
    mid_value = round(shares * mid_price, 4)

    unrealized_pnl_bid = round(conservative_exit_value - notional_usdc, 4)
    unrealized_pnl_mid = round(mid_value - notional_usdc, 4)

    roi_bid_pct = round((unrealized_pnl_bid / notional_usdc) * 100, 2) if notional_usdc else 0
    roi_mid_pct = round((unrealized_pnl_mid / notional_usdc) * 100, 2) if notional_usdc else 0

    return {
        "question": trade.get("question", ""),
        "outcome": trade.get("outcome", ""),
        "token_id": token_id,
        "entry_price": entry_price,
        "shares": shares,
        "notional_usdc": notional_usdc,
        "current_bid": current_bid,
        "current_ask": current_ask,
        "mid_price": mid_price,
        "exit_value_bid": conservative_exit_value,
        "mid_value": mid_value,
        "pnl_bid": unrealized_pnl_bid,
        "pnl_mid": unrealized_pnl_mid,
        "roi_bid_pct": roi_bid_pct,
        "roi_mid_pct": roi_mid_pct,
        "score": trade.get("score", ""),
        "grade": trade.get("grade", ""),
        "action": trade.get("action", ""),
        "created_at": trade.get("created_at", ""),
    }


def mark_open_trades_to_market() -> list[dict[str, Any]]:
    open_trades = get_open_paper_trades()

    if open_trades.empty:
        return []

    marked_rows = []

    for _, trade in open_trades.iterrows():
        try:
            marked_rows.append(mark_trade_to_market(trade.to_dict()))
        except Exception as error:
            marked_rows.append(
                {
                    "question": trade.get("question", ""),
                    "outcome": trade.get("outcome", ""),
                    "token_id": trade.get("token_id", ""),
                    "error": str(error),
                }
            )

    return marked_rows


def save_portfolio_snapshot(rows: list[dict[str, Any]]) -> Path:
    output_path = DATA_DIR / "paper_portfolio_snapshot.csv"

    if not rows:
        return output_path

    DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path, index=False)

    return output_path
