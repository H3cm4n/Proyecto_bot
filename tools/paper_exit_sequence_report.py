from __future__ import annotations

from pathlib import Path

import pandas as pd


TRADES = Path("data/paper_trades.csv")
JOURNAL = Path("data/candidate_journal.csv")
OUT = Path("data/paper_exit_sequence_audit.csv")


def safe_str(value) -> str:
    if value is None:
        return ""

    text = str(value)

    if text.lower() == "nan":
        return ""

    return text


def main() -> None:
    print("\n=== PAPER EXIT SEQUENCE REPORT ===")

    if not TRADES.exists() or not JOURNAL.exists():
        print("Falta data/paper_trades.csv o data/candidate_journal.csv")
        return

    trades = pd.read_csv(TRADES)
    journal = pd.read_csv(JOURNAL)

    if trades.empty or journal.empty:
        print("Trades o journal vacíos.")
        return

    trades["opened_at_dt"] = pd.to_datetime(trades["opened_at"], errors="coerce", utc=True)
    trades["closed_at_dt"] = pd.to_datetime(trades["closed_at"], errors="coerce", utc=True)

    journal["observed_at_dt"] = pd.to_datetime(journal["observed_at"], errors="coerce", utc=True)
    journal = journal.dropna(subset=["observed_at_dt"])

    for col in ["best_bid", "best_ask", "spread", "score", "fair_edge_to_ask"]:
        if col in journal.columns:
            journal[col] = pd.to_numeric(journal[col], errors="coerce")

    closed = trades[
        trades["status"].astype(str).eq("CLOSED")
        & trades["closed_at_dt"].notna()
        & trades["opened_at_dt"].notna()
    ].copy()

    rows_out = []

    for trade_idx, trade in closed.iterrows():
        symbol = safe_str(trade.get("crypto_symbol")).strip().upper()
        outcome = safe_str(trade.get("outcome")).strip()
        question = safe_str(trade.get("question")).strip()
        close_reason = safe_str(trade.get("close_reason")).strip()

        opened_at = trade["opened_at_dt"]
        closed_at = trade["closed_at_dt"]

        window = journal[
            journal["crypto_symbol"].astype(str).str.upper().eq(symbol)
            & journal["outcome"].astype(str).eq(outcome)
            & journal["question"].astype(str).eq(question)
            & (journal["observed_at_dt"] >= opened_at)
            & (journal["observed_at_dt"] <= closed_at)
        ].copy()

        if window.empty:
            continue

        window = window.sort_values("observed_at_dt").reset_index(drop=True)

        # Calcula racha final de "mala alineación": todo lo que no sea ALIGNED.
        last_bad_streak = 0

        for _, row in window.iloc[::-1].iterrows():
            alignment = safe_str(row.get("crypto_alignment")).upper()

            if alignment == "ALIGNED":
                break

            last_bad_streak += 1

        for seq_idx, row in window.tail(12).iterrows():
            minutes_from_open = (row["observed_at_dt"] - opened_at).total_seconds() / 60
            minutes_to_close = (closed_at - row["observed_at_dt"]).total_seconds() / 60

            rows_out.append(
                {
                    "trade_index": trade_idx,
                    "crypto_symbol": symbol,
                    "outcome": outcome,
                    "close_reason": close_reason,
                    "trade_entry_price": trade.get("entry_price"),
                    "trade_close_bid": trade.get("current_bid"),
                    "trade_pnl_pct": trade.get("pnl_pct"),
                    "trade_minutes_open": (closed_at - opened_at).total_seconds() / 60,
                    "last_bad_alignment_streak": last_bad_streak,
                    "observed_at": row.get("observed_at"),
                    "minutes_from_open": minutes_from_open,
                    "minutes_to_close": minutes_to_close,
                    "crypto_alignment": row.get("crypto_alignment"),
                    "binance_bias": row.get("binance_bias"),
                    "crypto_decision": row.get("crypto_decision"),
                    "crypto_decision_reasons": row.get("crypto_decision_reasons"),
                    "best_bid": row.get("best_bid"),
                    "best_ask": row.get("best_ask"),
                    "spread": row.get("spread"),
                    "score": row.get("score"),
                    "fair_edge_to_ask": row.get("fair_edge_to_ask"),
                    "question": question,
                }
            )

    if not rows_out:
        print("No se encontraron secuencias para auditar.")
        return

    out = pd.DataFrame(rows_out)
    out.to_csv(OUT, index=False)

    print(f"Archivo: {OUT}")

    risk = out[out["close_reason"].astype(str).eq("RISK_EXIT_BINANCE_NOT_ALIGNED")].copy()

    if risk.empty:
        print("No hay cierres RISK_EXIT_BINANCE_NOT_ALIGNED en la secuencia.")
        return

    cols = [
        "trade_index",
        "crypto_symbol",
        "outcome",
        "trade_pnl_pct",
        "trade_minutes_open",
        "last_bad_alignment_streak",
        "minutes_to_close",
        "crypto_alignment",
        "binance_bias",
        "crypto_decision",
        "best_bid",
        "best_ask",
        "score",
        "question",
    ]

    print("\n=== SECUENCIA DE CIERRES RISK_EXIT ===")
    print(risk[cols].to_string(index=False))


if __name__ == "__main__":
    main()
