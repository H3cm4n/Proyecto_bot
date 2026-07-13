from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


SNAPSHOT_PATH = "data/crypto_signal_snapshot_fair_value.csv"
TRADES_PATH = "data/paper_trades.csv"
CYCLE_JOURNAL_PATH = "data/cycle_journal.csv"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def count_value(df: pd.DataFrame, column: str, value: str) -> int:
    if df.empty or column not in df.columns:
        return 0
    return int(df[column].fillna("").astype(str).eq(value).sum())


def main() -> None:
    snapshot_path = Path(sys.argv[1] if len(sys.argv) > 1 else SNAPSHOT_PATH)
    trades_path = Path(os.getenv("PAPER_TRADES_PATH", TRADES_PATH))
    journal_path = Path(os.getenv("CYCLE_JOURNAL_PATH", CYCLE_JOURNAL_PATH))

    if not snapshot_path.exists():
        raise SystemExit(f"No existe snapshot: {snapshot_path}")

    snapshot = pd.read_csv(snapshot_path)
    trades = load_csv(trades_path)

    for col in [
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_probability",
        "fair_edge_to_ask",
        "binance_spot_price",
        "pnl_usd",
        "trade_usd",
    ]:
        if col in snapshot.columns:
            snapshot[col] = pd.to_numeric(snapshot[col], errors="coerce")
        if col in trades.columns:
            trades[col] = pd.to_numeric(trades[col], errors="coerce")

    decision_counts = (
        snapshot["crypto_decision"].fillna("").astype(str).value_counts().to_dict()
        if "crypto_decision" in snapshot.columns
        else {}
    )

    bias_counts = (
        snapshot[["crypto_symbol", "binance_bias"]]
        .drop_duplicates()
        .get("binance_bias", pd.Series(dtype=str))
        .fillna("")
        .astype(str)
        .value_counts()
        .to_dict()
        if {"crypto_symbol", "binance_bias"}.issubset(snapshot.columns)
        else {}
    )

    buy_rows = snapshot[
        snapshot.get("crypto_decision", pd.Series(dtype=str)).eq("CRYPTO_BUY_FAIR_EDGE")
    ].copy()

    watch_rows = snapshot[
        snapshot.get("crypto_decision", pd.Series(dtype=str)).eq("CRYPTO_WATCH_FAIR_EDGE")
    ].copy()

    open_trades = trades[trades.get("status", pd.Series(dtype=str)).eq("OPEN")] if not trades.empty else pd.DataFrame()
    closed_trades = trades[trades.get("status", pd.Series(dtype=str)).eq("CLOSED")] if not trades.empty else pd.DataFrame()

    paper_total_pnl = float(trades["pnl_usd"].fillna(0).sum()) if "pnl_usd" in trades.columns else 0.0
    paper_open_pnl = float(open_trades["pnl_usd"].fillna(0).sum()) if "pnl_usd" in open_trades.columns else 0.0
    paper_closed_pnl = float(closed_trades["pnl_usd"].fillna(0).sum()) if "pnl_usd" in closed_trades.columns else 0.0
    paper_open_exposure = float(open_trades["trade_usd"].fillna(0).sum()) if "trade_usd" in open_trades.columns else 0.0

    best_buy_edge = ""
    best_buy_question = ""
    best_buy_symbol = ""
    best_buy_outcome = ""

    if not buy_rows.empty and "fair_edge_to_ask" in buy_rows.columns:
        buy_rows = buy_rows.sort_values("fair_edge_to_ask", ascending=False, na_position="last")
        best = buy_rows.iloc[0]
        best_buy_edge = best.get("fair_edge_to_ask", "")
        best_buy_question = best.get("question", "")
        best_buy_symbol = best.get("crypto_symbol", "")
        best_buy_outcome = best.get("outcome", "")

    row = {
        "observed_at": now_iso(),
        "snapshot_rows": len(snapshot),
        "buy_count": len(buy_rows),
        "watch_count": len(watch_rows),
        "best_buy_edge": best_buy_edge,
        "best_buy_symbol": best_buy_symbol,
        "best_buy_outcome": best_buy_outcome,
        "best_buy_question": best_buy_question,
        "binance_bullish_symbols": int(bias_counts.get("BULLISH", 0)),
        "binance_bearish_symbols": int(bias_counts.get("BEARISH", 0)),
        "binance_neutral_symbols": int(bias_counts.get("NEUTRAL", 0)),
        "decision_buy": int(decision_counts.get("CRYPTO_BUY_FAIR_EDGE", 0)),
        "decision_watch": int(decision_counts.get("CRYPTO_WATCH_FAIR_EDGE", 0)),
        "decision_wait_not_aligned": int(decision_counts.get("CRYPTO_WAIT_BINANCE_NOT_ALIGNED", 0)),
        "decision_conflict": int(decision_counts.get("CRYPTO_AVOID_BINANCE_CONFLICT", 0)),
        "decision_incomplete_orderbook": int(decision_counts.get("CRYPTO_IGNORE_INCOMPLETE_ORDERBOOK", 0)),
        "decision_threshold_too_far": int(decision_counts.get("CRYPTO_IGNORE_THRESHOLD_TOO_FAR", 0)),
        "paper_open_trades": len(open_trades),
        "paper_closed_trades": len(closed_trades),
        "paper_open_exposure_usd": paper_open_exposure,
        "paper_total_pnl_usd": paper_total_pnl,
        "paper_open_pnl_usd": paper_open_pnl,
        "paper_closed_pnl_usd": paper_closed_pnl,
    }

    journal_path.parent.mkdir(parents=True, exist_ok=True)
    old = load_csv(journal_path)
    new = pd.DataFrame([row])

    if old.empty:
        out = new
    else:
        out = pd.concat([old, new], ignore_index=True)

    out.to_csv(journal_path, index=False)

    print("\n=== CYCLE JOURNAL ===")
    print(f"Ciclo registrado: {row['observed_at']}")
    print(f"BUY: {row['buy_count']} | WATCH: {row['watch_count']}")
    print(
        f"Binance BULLISH/BEARISH/NEUTRAL: "
        f"{row['binance_bullish_symbols']}/"
        f"{row['binance_bearish_symbols']}/"
        f"{row['binance_neutral_symbols']}"
    )
    print(
        f"Paper open/closed: {row['paper_open_trades']}/"
        f"{row['paper_closed_trades']} | "
        f"PnL total: ${row['paper_total_pnl_usd']:.4f}"
    )
    print(f"Archivo: {journal_path}")


if __name__ == "__main__":
    main()
