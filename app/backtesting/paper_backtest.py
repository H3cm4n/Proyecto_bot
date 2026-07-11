from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from app.backtesting.replay_audit import (
    load_replay_history,
    run_replay_audit,
    safe_float,
    safe_str,
)


DEFAULT_HISTORY_PATH = Path("data/orderbook_history.csv")
DEFAULT_TRADES_OUTPUT_PATH = Path("data/backtest_trades.csv")


def prepare_history(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return history

    df = history.copy()
    df["observed_dt"] = pd.to_datetime(df.get("observed_at", ""), utc=True, errors="coerce")
    df["best_bid_num"] = df.get("best_bid", "").apply(safe_float)
    df["best_ask_num"] = df.get("best_ask", "").apply(safe_float)
    df["spread_num"] = df.get("spread", "").apply(safe_float)

    return df.dropna(subset=["observed_dt"]).sort_values("observed_dt")


def compute_trade_values(entry_price: float, exit_price: float, usdc_amount: float) -> dict[str, float]:
    if entry_price <= 0:
        return {
            "shares": 0.0,
            "exit_value_usdc": 0.0,
            "pnl_usdc": 0.0,
            "roi_pct": 0.0,
        }

    shares = usdc_amount / entry_price
    exit_value = shares * exit_price
    pnl = exit_value - usdc_amount
    roi = (pnl / usdc_amount) * 100 if usdc_amount > 0 else 0.0

    return {
        "shares": round(shares, 4),
        "exit_value_usdc": round(exit_value, 4),
        "pnl_usdc": round(pnl, 4),
        "roi_pct": round(roi, 2),
    }


def simulate_trade_exit(
    signal: dict[str, Any],
    token_history: pd.DataFrame,
    usdc_amount: float = 5.0,
    stop_loss_pct: float = -20.0,
    take_profit_pct: float = 25.0,
) -> dict[str, Any]:
    entry_time = pd.to_datetime(signal.get("observed_at", ""), utc=True, errors="coerce")
    entry_price = safe_float(signal.get("ask"))
    entry_bid = safe_float(signal.get("bid"))

    if pd.isna(entry_time):
        return {
            "exit_time": "",
            "exit_price": entry_bid,
            "exit_reason": "BAD_ENTRY_TIME",
            "holding_observations": 0,
        }

    future = token_history[token_history["observed_dt"] > entry_time].sort_values("observed_dt")

    exit_time = entry_time
    exit_price = entry_bid
    exit_reason = "END_OF_HISTORY"
    holding_observations = 0

    if future.empty:
        exit_reason = "NO_FUTURE_DATA"
    else:
        for _, row in future.iterrows():
            bid = safe_float(row.get("best_bid"))

            if bid <= 0:
                continue

            holding_observations += 1
            values = compute_trade_values(entry_price, bid, usdc_amount)
            roi = values["roi_pct"]

            exit_time = row.get("observed_dt")
            exit_price = bid

            if roi <= stop_loss_pct:
                exit_reason = "STOP_LOSS"
                break

            if roi >= take_profit_pct:
                exit_reason = "TAKE_PROFIT"
                break

    values = compute_trade_values(entry_price, exit_price, usdc_amount)

    return {
        "exit_time": str(exit_time),
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "holding_observations": holding_observations,
        **values,
    }


def build_backtest_trade(
    signal: dict[str, Any],
    exit_data: dict[str, Any],
    usdc_amount: float,
) -> dict[str, Any]:
    return {
        "entry_time": safe_str(signal.get("observed_at")),
        "exit_time": safe_str(exit_data.get("exit_time")),
        "exit_reason": safe_str(exit_data.get("exit_reason")),
        "holding_observations": exit_data.get("holding_observations", 0),
        "question": safe_str(signal.get("question")),
        "outcome": safe_str(signal.get("outcome")),
        "token_id": safe_str(signal.get("token_id")),
        "entry_price": safe_float(signal.get("ask")),
        "exit_price": safe_float(exit_data.get("exit_price")),
        "shares": safe_float(exit_data.get("shares")),
        "notional_usdc": usdc_amount,
        "exit_value_usdc": safe_float(exit_data.get("exit_value_usdc")),
        "pnl_usdc": safe_float(exit_data.get("pnl_usdc")),
        "roi_pct": safe_float(exit_data.get("roi_pct")),
        "score": signal.get("score", ""),
        "action": signal.get("action", ""),
        "edge_score": signal.get("edge_score", ""),
        "edge_action": signal.get("edge_action", ""),
        "edge_mid_delta": signal.get("edge_mid_delta", ""),
        "relative_spread_pct": signal.get("relative_spread_pct", ""),
    }


def summarize_backtest(trades: list[dict[str, Any]], selected_signals: int, skipped_duplicates: int) -> dict[str, Any]:
    total_trades = len(trades)
    invested = sum(safe_float(row.get("notional_usdc")) for row in trades)
    exit_value = sum(safe_float(row.get("exit_value_usdc")) for row in trades)
    pnl = sum(safe_float(row.get("pnl_usdc")) for row in trades)
    roi = (pnl / invested) * 100 if invested > 0 else 0.0

    wins = sum(1 for row in trades if safe_float(row.get("pnl_usdc")) > 0)
    losses = sum(1 for row in trades if safe_float(row.get("pnl_usdc")) < 0)
    breakeven = total_trades - wins - losses
    winrate = (wins / total_trades) * 100 if total_trades > 0 else 0.0

    exit_reasons = Counter(safe_str(row.get("exit_reason")) for row in trades)

    best_trade = max(trades, key=lambda row: safe_float(row.get("roi_pct")), default=None)
    worst_trade = min(trades, key=lambda row: safe_float(row.get("roi_pct")), default=None)

    return {
        "selected_signals": selected_signals,
        "skipped_duplicate_questions": skipped_duplicates,
        "total_trades": total_trades,
        "invested_usdc": round(invested, 4),
        "exit_value_usdc": round(exit_value, 4),
        "pnl_usdc": round(pnl, 4),
        "roi_pct": round(roi, 2),
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "winrate_pct": round(winrate, 2),
        "exit_reason_counts": dict(exit_reasons),
        "best_trade": best_trade,
        "worst_trade": worst_trade,
    }


def save_backtest_trades(trades: list[dict[str, Any]], output_path: Path = DEFAULT_TRADES_OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(trades).to_csv(output_path, index=False)


def run_signal_backtest(
    history_path: Path = DEFAULT_HISTORY_PATH,
    output_path: Path = DEFAULT_TRADES_OUTPUT_PATH,
    usdc_amount: float = 5.0,
    min_score: int = 80,
    min_edge_score: int = 65,
    min_edge_mid_delta: float = 0.005,
    proposal_limit: int = 3,
    stop_loss_pct: float = -20.0,
    take_profit_pct: float = 25.0,
    min_entry_price: float = 0.05,
    max_entry_price: float = 0.90,
    min_top_liquidity: float = 10.0,
    max_relative_spread_pct: float = 10.0,
    avoid_duplicate_questions: bool = True,
    save_output: bool = True,
) -> dict[str, Any]:
    history = prepare_history(load_replay_history(history_path))

    replay = run_replay_audit(
        history_path=history_path,
        min_score=min_score,
        min_edge_score=min_edge_score,
        min_edge_mid_delta=min_edge_mid_delta,
        proposal_limit=proposal_limit,
        min_entry_price=min_entry_price,
        max_entry_price=max_entry_price,
        min_top_liquidity=min_top_liquidity,
        max_relative_spread_pct=max_relative_spread_pct,
        save_output=False,
    )

    selected_signals = [
        row for row in replay.get("rows", [])
        if row.get("decision") == "SELECTED"
    ]

    selected_signals = sorted(
        selected_signals,
        key=lambda row: safe_str(row.get("observed_at")),
    )

    seen_questions: set[str] = set()
    skipped_duplicates = 0
    trades: list[dict[str, Any]] = []

    for signal in selected_signals:
        question = safe_str(signal.get("question"))
        token_id = safe_str(signal.get("token_id"))

        if avoid_duplicate_questions and question in seen_questions:
            skipped_duplicates += 1
            continue

        seen_questions.add(question)

        token_history = history[history.get("token_id", "") == token_id]

        exit_data = simulate_trade_exit(
            signal=signal,
            token_history=token_history,
            usdc_amount=usdc_amount,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
        )

        trades.append(
            build_backtest_trade(
                signal=signal,
                exit_data=exit_data,
                usdc_amount=usdc_amount,
            )
        )

    if save_output:
        save_backtest_trades(trades, output_path)

    return {
        "history_path": str(history_path),
        "output_path": str(output_path),
        "trades": trades,
        "summary": summarize_backtest(
            trades=trades,
            selected_signals=len(selected_signals),
            skipped_duplicates=skipped_duplicates,
        ),
    }
