from __future__ import annotations

from pathlib import Path
import os

import pandas as pd


PATH = Path(os.getenv("RESEARCH_PAPER_TRADES_PATH", "data/research_paper_trades.csv"))


def main() -> None:
    print("\n=== RESEARCH PAPER REPORT ===")

    if not PATH.exists():
        print(f"No existe {PATH}")
        return

    try:
        df = pd.read_csv(PATH)
    except pd.errors.EmptyDataError:
        print("research_paper_trades.csv está vacío.")
        return

    if df.empty:
        print("research_paper_trades.csv está vacío.")
        return

    for col in ["trade_usd", "current_value_usd", "pnl_usd", "pnl_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    total = len(df)
    open_count = int((df["status"].astype(str) == "OPEN").sum())
    closed_count = int((df["status"].astype(str) == "CLOSED").sum())

    closed = df[df["status"].astype(str) == "CLOSED"].copy()
    open_df = df[df["status"].astype(str) == "OPEN"].copy()

    total_pnl = df["pnl_usd"].sum() if "pnl_usd" in df.columns else 0.0
    closed_pnl = closed["pnl_usd"].sum() if not closed.empty else 0.0
    open_pnl = open_df["pnl_usd"].sum() if not open_df.empty else 0.0
    exposure = open_df["trade_usd"].sum() if not open_df.empty else 0.0

    wins = int((closed["pnl_usd"] > 0).sum()) if not closed.empty else 0
    losses = int((closed["pnl_usd"] < 0).sum()) if not closed.empty else 0
    flat = int((closed["pnl_usd"] == 0).sum()) if not closed.empty else 0
    win_rate = (wins / len(closed) * 100) if len(closed) else 0.0

    print(f"Trades totales: {total}")
    print(f"Abiertos: {open_count}")
    print(f"Cerrados: {closed_count}")
    print(f"Exposición abierta: ${exposure:.4f}")
    print(f"PnL total marcado: ${total_pnl:.4f}")
    print(f"PnL cerrado: ${closed_pnl:.4f}")
    print(f"PnL abierto: ${open_pnl:.4f}")
    print(f"Win rate cerrado: {win_rate:.2f}%")
    print(f"Wins/Losses/Flat: {wins}/{losses}/{flat}")

    if "close_reason" in df.columns:
        print("\n=== CIERRES POR RAZÓN ===")
        print(df["close_reason"].fillna("OPEN_OR_NONE").replace("", "OPEN_OR_NONE").value_counts().to_string())

    if "flow_support" in df.columns:
        print("\n=== PNL POR FLOW SUPPORT ===")
        print(df.groupby("flow_support", dropna=False)["pnl_usd"].sum().to_string())

    if "crypto_decision" in df.columns:
        print("\n=== PNL POR DECISIÓN ===")
        print(df.groupby("crypto_decision", dropna=False)["pnl_usd"].sum().to_string())

    print("\n=== ÚLTIMOS RESEARCH TRADES ===")
    cols = [
        "status",
        "strategy",
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
    cols = [col for col in cols if col in df.columns]
    print(df[cols].tail(20).to_string(index=False))


if __name__ == "__main__":
    main()
