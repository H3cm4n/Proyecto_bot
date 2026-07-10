from pathlib import Path
from typing import Any

import pandas as pd

from app.execution.paper_portfolio import mark_open_trades_to_market


DATA_DIR = Path("data")
TRADES_PATH = DATA_DIR / "paper_trades.csv"
REPORT_PATH = DATA_DIR / "paper_performance_report.csv"


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def pct(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0

    return round((numerator / denominator) * 100, 2)


def load_trades() -> pd.DataFrame:
    if not TRADES_PATH.exists():
        return pd.DataFrame()

    return pd.read_csv(TRADES_PATH, dtype=str).fillna("")


def summarize_closed_trades(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty or "status" not in df.columns:
        return {
            "closed_trade_count": 0,
            "closed_invested_usdc": 0.0,
            "closed_pnl_usdc": 0.0,
            "closed_roi_pct": 0.0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "winrate_pct": 0.0,
            "loss_rate_pct": 0.0,
            "avg_closed_roi_pct": 0.0,
            "best_trade": None,
            "worst_trade": None,
            "exit_reason_counts": {},
        }

    closed = df[df["status"].astype(str).str.upper() == "CLOSED"].copy()

    if closed.empty:
        return {
            "closed_trade_count": 0,
            "closed_invested_usdc": 0.0,
            "closed_pnl_usdc": 0.0,
            "closed_roi_pct": 0.0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "winrate_pct": 0.0,
            "loss_rate_pct": 0.0,
            "avg_closed_roi_pct": 0.0,
            "best_trade": None,
            "worst_trade": None,
            "exit_reason_counts": {},
        }

    closed["notional_usdc_num"] = closed.get("notional_usdc", 0).apply(safe_float)
    closed["realized_pnl_usdc_num"] = closed.get("realized_pnl_usdc", 0).apply(safe_float)
    closed["realized_roi_pct_num"] = closed.get("realized_roi_pct", 0).apply(safe_float)

    closed_trade_count = len(closed)
    closed_invested_usdc = round(float(closed["notional_usdc_num"].sum()), 4)
    closed_pnl_usdc = round(float(closed["realized_pnl_usdc_num"].sum()), 4)
    closed_roi_pct = pct(closed_pnl_usdc, closed_invested_usdc)

    wins = int((closed["realized_pnl_usdc_num"] > 0).sum())
    losses = int((closed["realized_pnl_usdc_num"] < 0).sum())
    breakeven = int((closed["realized_pnl_usdc_num"] == 0).sum())

    winrate_pct = pct(wins, closed_trade_count)
    loss_rate_pct = pct(losses, closed_trade_count)

    avg_closed_roi_pct = round(float(closed["realized_roi_pct_num"].mean()), 2)

    best_idx = closed["realized_pnl_usdc_num"].idxmax()
    worst_idx = closed["realized_pnl_usdc_num"].idxmin()

    best_trade = closed.loc[best_idx].to_dict()
    worst_trade = closed.loc[worst_idx].to_dict()

    exit_reason_counts = (
        closed.get("exit_reason", pd.Series(dtype=str))
        .replace("", "UNKNOWN")
        .value_counts()
        .to_dict()
    )

    return {
        "closed_trade_count": closed_trade_count,
        "closed_invested_usdc": closed_invested_usdc,
        "closed_pnl_usdc": closed_pnl_usdc,
        "closed_roi_pct": closed_roi_pct,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "winrate_pct": winrate_pct,
        "loss_rate_pct": loss_rate_pct,
        "avg_closed_roi_pct": avg_closed_roi_pct,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "exit_reason_counts": exit_reason_counts,
    }


def summarize_open_positions() -> dict[str, Any]:
    open_rows = mark_open_trades_to_market()

    if not open_rows:
        return {
            "open_trade_count": 0,
            "open_exposure_usdc": 0.0,
            "open_value_bid_usdc": 0.0,
            "open_unrealized_pnl_bid_usdc": 0.0,
            "open_unrealized_roi_bid_pct": 0.0,
            "open_positions": [],
        }

    open_exposure_usdc = round(
        sum(safe_float(row.get("notional_usdc")) for row in open_rows),
        4,
    )
    open_value_bid_usdc = round(
        sum(safe_float(row.get("exit_value_bid")) for row in open_rows),
        4,
    )
    open_unrealized_pnl_bid_usdc = round(
        sum(safe_float(row.get("pnl_bid")) for row in open_rows),
        4,
    )
    open_unrealized_roi_bid_pct = pct(
        open_unrealized_pnl_bid_usdc,
        open_exposure_usdc,
    )

    return {
        "open_trade_count": len(open_rows),
        "open_exposure_usdc": open_exposure_usdc,
        "open_value_bid_usdc": open_value_bid_usdc,
        "open_unrealized_pnl_bid_usdc": open_unrealized_pnl_bid_usdc,
        "open_unrealized_roi_bid_pct": open_unrealized_roi_bid_pct,
        "open_positions": open_rows,
    }


def build_performance_report() -> dict[str, Any]:
    df = load_trades()

    if df.empty:
        return {
            "message": "No hay trades PAPER registrados.",
            "closed_trade_count": 0,
            "open_trade_count": 0,
            "closed_invested_usdc": 0.0,
            "closed_pnl_usdc": 0.0,
            "closed_roi_pct": 0.0,
            "open_exposure_usdc": 0.0,
            "open_value_bid_usdc": 0.0,
            "open_unrealized_pnl_bid_usdc": 0.0,
            "open_unrealized_roi_bid_pct": 0.0,
            "total_deployed_usdc": 0.0,
            "total_paper_pnl_usdc": 0.0,
            "total_paper_roi_pct": 0.0,
            "wins": 0,
            "losses": 0,
            "breakeven": 0,
            "winrate_pct": 0.0,
            "loss_rate_pct": 0.0,
            "avg_closed_roi_pct": 0.0,
            "best_trade": None,
            "worst_trade": None,
            "exit_reason_counts": {},
            "open_positions": [],
        }

    closed_summary = summarize_closed_trades(df)
    open_summary = summarize_open_positions()

    total_deployed_usdc = round(
        safe_float(closed_summary.get("closed_invested_usdc"))
        + safe_float(open_summary.get("open_exposure_usdc")),
        4,
    )

    total_paper_pnl_usdc = round(
        safe_float(closed_summary.get("closed_pnl_usdc"))
        + safe_float(open_summary.get("open_unrealized_pnl_bid_usdc")),
        4,
    )

    total_paper_roi_pct = pct(total_paper_pnl_usdc, total_deployed_usdc)

    return {
        **closed_summary,
        **open_summary,
        "total_deployed_usdc": total_deployed_usdc,
        "total_paper_pnl_usdc": total_paper_pnl_usdc,
        "total_paper_roi_pct": total_paper_roi_pct,
    }


def save_performance_report(report: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)

    flat_report = {
        key: value
        for key, value in report.items()
        if key not in {"best_trade", "worst_trade", "exit_reason_counts", "open_positions"}
    }

    pd.DataFrame([flat_report]).to_csv(REPORT_PATH, index=False)
