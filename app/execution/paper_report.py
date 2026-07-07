from pathlib import Path
from typing import Any

import pandas as pd


DATA_DIR = Path("data")
PAPER_TRADES_PATH = DATA_DIR / "paper_trades.csv"


def load_trades() -> pd.DataFrame:
    if not PAPER_TRADES_PATH.exists():
        return pd.DataFrame()

    return pd.read_csv(PAPER_TRADES_PATH)


def build_performance_report() -> dict[str, Any]:
    df = load_trades()

    if df.empty:
        return {
            "has_data": False,
            "message": "No hay trades PAPER registrados.",
        }

    closed_df = df[df["status"] == "CLOSED"].copy() if "status" in df.columns else pd.DataFrame()
    open_df = df[df["status"] == "OPEN"].copy() if "status" in df.columns else pd.DataFrame()

    if closed_df.empty:
        return {
            "has_data": True,
            "closed_trades": 0,
            "open_trades": len(open_df),
            "message": "Hay trades, pero ninguno cerrado todavía.",
        }

    closed_df["notional_usdc"] = pd.to_numeric(closed_df["notional_usdc"], errors="coerce").fillna(0)
    closed_df["realized_pnl_usdc"] = pd.to_numeric(closed_df["realized_pnl_usdc"], errors="coerce").fillna(0)
    closed_df["realized_roi_pct"] = pd.to_numeric(closed_df["realized_roi_pct"], errors="coerce").fillna(0)

    total_invested = round(float(closed_df["notional_usdc"].sum()), 4)
    total_pnl = round(float(closed_df["realized_pnl_usdc"].sum()), 4)
    total_roi = round((total_pnl / total_invested) * 100, 2) if total_invested else 0

    wins = closed_df[closed_df["realized_pnl_usdc"] > 0]
    losses = closed_df[closed_df["realized_pnl_usdc"] < 0]
    breakeven = closed_df[closed_df["realized_pnl_usdc"] == 0]

    closed_count = len(closed_df)
    winrate = round((len(wins) / closed_count) * 100, 2) if closed_count else 0
    loss_rate = round((len(losses) / closed_count) * 100, 2) if closed_count else 0

    best_trade = closed_df.sort_values("realized_pnl_usdc", ascending=False).head(1).to_dict("records")[0]
    worst_trade = closed_df.sort_values("realized_pnl_usdc", ascending=True).head(1).to_dict("records")[0]

    exit_reason_counts = (
        closed_df["exit_reason"]
        .fillna("UNKNOWN")
        .value_counts()
        .to_dict()
        if "exit_reason" in closed_df.columns
        else {}
    )

    return {
        "has_data": True,
        "closed_trades": closed_count,
        "open_trades": len(open_df),
        "total_invested": total_invested,
        "total_pnl": total_pnl,
        "total_roi_pct": total_roi,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "winrate_pct": winrate,
        "loss_rate_pct": loss_rate,
        "avg_roi_pct": round(float(closed_df["realized_roi_pct"].mean()), 2),
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "exit_reason_counts": exit_reason_counts,
    }


def save_performance_report(report: dict[str, Any]) -> Path:
    output_path = DATA_DIR / "paper_performance_report.csv"

    if not report.get("has_data"):
        return output_path

    summary = {
        key: value
        for key, value in report.items()
        if key not in {"best_trade", "worst_trade", "exit_reason_counts"}
    }

    DATA_DIR.mkdir(exist_ok=True)
    pd.DataFrame([summary]).to_csv(output_path, index=False)

    return output_path
