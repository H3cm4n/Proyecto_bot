from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


DEFAULT_PATH = "data/cycle_journal.csv"


def money(value) -> str:
    try:
        return f"${float(value):.4f}"
    except Exception:
        return "$0.0000"


def pct(value) -> str:
    try:
        return f"{float(value):.2f}%"
    except Exception:
        return "0.00%"


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)

    if not path.exists():
        print(f"No existe cycle journal: {path}")
        return

    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        print("cycle_journal.csv está vacío.")
        return

    if df.empty:
        print("No hay ciclos registrados todavía.")
        return

    numeric_cols = [
        "snapshot_rows",
        "buy_count",
        "watch_count",
        "best_buy_edge",
        "binance_bullish_symbols",
        "binance_bearish_symbols",
        "binance_neutral_symbols",
        "decision_buy",
        "decision_watch",
        "decision_wait_not_aligned",
        "decision_conflict",
        "decision_incomplete_orderbook",
        "decision_threshold_too_far",
        "paper_open_trades",
        "paper_closed_trades",
        "paper_open_exposure_usd",
        "paper_total_pnl_usd",
        "paper_open_pnl_usd",
        "paper_closed_pnl_usd",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "observed_at" in df.columns:
        df["observed_at_dt"] = pd.to_datetime(df["observed_at"], utc=True, errors="coerce")
        valid_times = df["observed_at_dt"].dropna()
    else:
        valid_times = pd.Series(dtype="datetime64[ns, UTC]")

    cycles = len(df)
    buy_cycles = int((df.get("buy_count", 0).fillna(0) > 0).sum()) if "buy_count" in df.columns else 0
    watch_cycles = int((df.get("watch_count", 0).fillna(0) > 0).sum()) if "watch_count" in df.columns else 0

    total_buy_signals = int(df["buy_count"].fillna(0).sum()) if "buy_count" in df.columns else 0
    total_watch_signals = int(df["watch_count"].fillna(0).sum()) if "watch_count" in df.columns else 0

    bullish_cycles = int((df.get("binance_bullish_symbols", 0).fillna(0) > 0).sum()) if "binance_bullish_symbols" in df.columns else 0
    neutral_only_cycles = int(
        (
            df.get("binance_neutral_symbols", 0).fillna(0).eq(4)
        ).sum()
    ) if "binance_neutral_symbols" in df.columns else 0

    latest_pnl = df["paper_total_pnl_usd"].dropna().iloc[-1] if "paper_total_pnl_usd" in df.columns and not df["paper_total_pnl_usd"].dropna().empty else 0
    min_pnl = df["paper_total_pnl_usd"].min() if "paper_total_pnl_usd" in df.columns else 0
    max_pnl = df["paper_total_pnl_usd"].max() if "paper_total_pnl_usd" in df.columns else 0

    print("\n=== CYCLE PERFORMANCE REPORT ===")
    print(f"Ciclos registrados: {cycles}")

    if not valid_times.empty:
        print(f"Primer ciclo: {valid_times.min()}")
        print(f"Último ciclo: {valid_times.max()}")

    print(f"Ciclos con BUY: {buy_cycles}")
    print(f"Ciclos con WATCH: {watch_cycles}")
    print(f"Señales BUY totales: {total_buy_signals}")
    print(f"Señales WATCH totales: {total_watch_signals}")
    print(f"Ciclos con algún Binance BULLISH: {bullish_cycles}")
    print(f"Ciclos con todos NEUTRAL: {neutral_only_cycles}")
    print(f"PnL paper actual: {money(latest_pnl)}")
    print(f"Mejor PnL visto: {money(max_pnl)}")
    print(f"Peor PnL visto: {money(min_pnl)}")

    if cycles:
        print(f"Frecuencia de ciclos con BUY: {pct(buy_cycles / cycles * 100)}")

    print("\n=== DECISIONES ACUMULADAS ===")
    decision_cols = [
        "decision_buy",
        "decision_watch",
        "decision_wait_not_aligned",
        "decision_conflict",
        "decision_incomplete_orderbook",
        "decision_threshold_too_far",
    ]

    for col in decision_cols:
        if col in df.columns:
            print(f"{col}: {int(df[col].fillna(0).sum())}")

    print("\n=== ÚLTIMOS CICLOS ===")
    cols = [
        "observed_at",
        "buy_count",
        "watch_count",
        "binance_bullish_symbols",
        "binance_bearish_symbols",
        "binance_neutral_symbols",
        "paper_open_trades",
        "paper_closed_trades",
        "paper_total_pnl_usd",
        "best_buy_symbol",
        "best_buy_outcome",
        "best_buy_edge",
        "best_buy_question",
    ]
    cols = [c for c in cols if c in df.columns]
    print(df.tail(10)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
