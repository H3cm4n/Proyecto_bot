from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Any

import pandas as pd

from app.backtesting.portfolio_backtest import run_portfolio_backtest


def parse_number_list(value: str, cast_type=float) -> list:
    """Parse comma-separated CLI values like '70,75,80'."""
    if not value:
        return []

    parsed = []
    for item in str(value).split(","):
        item = item.strip()
        if not item:
            continue
        parsed.append(cast_type(item))

    return parsed


def run_parameter_sweep(
    history_path: Path,
    output_path: Path,
    scores: list[int],
    edges: list[int],
    deltas: list[float],
    cooldowns: list[int],
    max_event_group_positions_values: list[int],
    initial_capital: float = 100.0,
    paper_size: float = 5.0,
    max_open_positions: int = 3,
    max_total_exposure: float = 15.0,
    stop_loss: float = -20.0,
    take_profit: float = 25.0,
    min_entry_price: float = 0.05,
    max_entry_price: float = 0.90,
    min_top_liquidity: float = 10.0,
    max_relative_spread_pct: float = 10.0,
    max_new_trades_per_cycle: int = 1,
) -> dict[str, Any]:
    """
    Run portfolio-backtest across many parameter combinations.

    Safe:
    - no API
    - no wallet
    - no live trading
    - does not modify paper_trades.csv
    - writes only sweep CSV output
    """

    rows: list[dict[str, Any]] = []

    combinations = list(
        product(
            scores,
            edges,
            deltas,
            cooldowns,
            max_event_group_positions_values,
        )
    )

    for idx, (
        score,
        edge,
        delta,
        cooldown,
        max_event_group_positions,
    ) in enumerate(combinations, start=1):
        result = run_portfolio_backtest(
            history_path=history_path,
            trades_output_path=Path("data/_tmp_sweep_trades.csv"),
            equity_output_path=Path("data/_tmp_sweep_equity.csv"),
            profile="custom",
            paper_min_score=int(score),
            paper_min_edge=int(edge),
            paper_min_edge_delta=float(delta),
            initial_capital=initial_capital,
            paper_size=paper_size,
            max_open_positions=max_open_positions,
            max_total_exposure=max_total_exposure,
            stop_loss=stop_loss,
            take_profit=take_profit,
            min_entry_price=min_entry_price,
            max_entry_price=max_entry_price,
            min_top_liquidity=min_top_liquidity,
            max_relative_spread_pct=max_relative_spread_pct,
            max_new_trades_per_cycle=max_new_trades_per_cycle,
            max_event_group_positions=int(max_event_group_positions),
            event_cooldown_cycles=int(cooldown),
            save_output=False,
        )

        summary = result.get("summary", {})

        rows.append(
            {
                "run": idx,
                "paper_min_score": int(score),
                "paper_min_edge": int(edge),
                "paper_min_edge_delta": float(delta),
                "event_cooldown_cycles": int(cooldown),
                "max_event_group_positions": int(max_event_group_positions),
                "initial_capital": initial_capital,
                "paper_size": paper_size,
                "max_open_positions": max_open_positions,
                "max_total_exposure": max_total_exposure,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "trades": int(summary.get("total_trades", 0)),
                "wins": int(summary.get("wins", 0)),
                "losses": int(summary.get("losses", 0)),
                "breakeven": int(summary.get("breakeven", 0)),
                "winrate_pct": float(summary.get("winrate_pct", 0.0)),
                "final_capital": float(summary.get("final_capital", initial_capital)),
                "total_pnl": float(summary.get("total_pnl", 0.0)),
                "total_roi_pct": float(summary.get("total_roi_pct", 0.0)),
                "max_drawdown": float(summary.get("max_drawdown", 0.0)),
                "max_exposure_used": float(summary.get("max_exposure_used", 0.0)),
                "max_positions_open": int(summary.get("max_positions_open", 0)),
                "event_group_rejects": int(summary.get("event_group_rejects", 0)),
                "cooldown_rejects": int(summary.get("cooldown_rejects", 0)),
            }
        )

    df = pd.DataFrame(rows)

    if not df.empty:
        # Prefer profitable, then lower drawdown, then more trades.
        df = df.sort_values(
            by=["total_roi_pct", "max_drawdown", "trades"],
            ascending=[False, True, False],
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)

    return {
        "history_path": str(history_path),
        "output_path": str(output_path),
        "runs": len(rows),
        "results": df.to_dict(orient="records"),
    }
