from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


DEFAULT_PATH = "data/paper_trades.csv"


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
        print(f"No existe paper trades file: {path}")
        return

    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        print("paper_trades.csv está vacío.")
        return

    if df.empty:
        print("No hay trades paper todavía.")
        return

    numeric_cols = [
        "entry_price",
        "current_bid",
        "current_ask",
        "trade_usd",
        "shares",
        "current_value_usd",
        "pnl_usd",
        "pnl_pct",
        "take_profit_price",
        "stop_loss_price",
        "fair_probability",
        "fair_edge_to_ask",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "status" not in df.columns:
        df["status"] = "UNKNOWN"

    open_df = df[df["status"].eq("OPEN")]
    closed_df = df[df["status"].eq("CLOSED")]

    total_trades = len(df)
    open_count = len(open_df)
    closed_count = len(closed_df)

    total_committed = df["trade_usd"].fillna(0).sum() if "trade_usd" in df.columns else 0
    open_exposure = open_df["trade_usd"].fillna(0).sum() if "trade_usd" in open_df.columns else 0

    total_pnl = df["pnl_usd"].fillna(0).sum() if "pnl_usd" in df.columns else 0
    closed_pnl = closed_df["pnl_usd"].fillna(0).sum() if "pnl_usd" in closed_df.columns else 0
    open_pnl = open_df["pnl_usd"].fillna(0).sum() if "pnl_usd" in open_df.columns else 0

    wins = len(closed_df[closed_df["pnl_usd"] > 0]) if "pnl_usd" in closed_df.columns else 0
    losses = len(closed_df[closed_df["pnl_usd"] < 0]) if "pnl_usd" in closed_df.columns else 0
    flats = len(closed_df[closed_df["pnl_usd"].fillna(0).eq(0)]) if "pnl_usd" in closed_df.columns else 0

    win_rate = (wins / closed_count * 100) if closed_count else 0

    print("\n=== PAPER PERFORMANCE REPORT ===")
    print(f"Trades totales: {total_trades}")
    print(f"Abiertos: {open_count}")
    print(f"Cerrados: {closed_count}")
    print(f"Capital simulado usado total: {money(total_committed)}")
    print(f"Exposición abierta actual: {money(open_exposure)}")
    print(f"PnL total marcado: {money(total_pnl)}")
    print(f"PnL cerrado: {money(closed_pnl)}")
    print(f"PnL abierto: {money(open_pnl)}")
    print(f"Win rate cerrado: {pct(win_rate)}")
    print(f"Wins/Losses/Flat: {wins}/{losses}/{flats}")

    if "close_reason" in df.columns:
        print("\n=== CIERRES POR RAZÓN ===")
        reasons = df["close_reason"].fillna("").replace("", "OPEN_OR_NONE").value_counts()
        print(reasons.to_string())

    if "crypto_symbol" in df.columns:
        print("\n=== PNL POR SÍMBOLO ===")
        by_symbol = (
            df.groupby("crypto_symbol", dropna=False)["pnl_usd"]
            .sum()
            .sort_values(ascending=False)
        )
        print(by_symbol.to_string())

    print("\n=== ÚLTIMOS TRADES ===")
    cols = [
        "status",
        "crypto_symbol",
        "outcome",
        "entry_price",
        "current_bid",
        "current_ask",
        "trade_usd",
        "pnl_usd",
        "pnl_pct",
        "close_reason",
        "question",
    ]
    cols = [c for c in cols if c in df.columns]
    print(df.tail(10)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
