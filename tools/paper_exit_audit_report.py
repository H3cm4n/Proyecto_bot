from __future__ import annotations

from pathlib import Path

import pandas as pd


TRADES = Path("data/paper_trades.csv")
JOURNAL = Path("data/candidate_journal.csv")


def safe_str(value) -> str:
    if value is None:
        return ""

    text = str(value)

    if text.lower() == "nan":
        return ""

    return text


def signal_key_from_trade(row) -> str:
    return "|".join(
        [
            safe_str(row.get("crypto_symbol")).strip(),
            safe_str(row.get("outcome")).strip(),
            safe_str(row.get("question")).strip(),
        ]
    )


def main() -> None:
    print("\n=== PAPER EXIT AUDIT REPORT ===")

    if not TRADES.exists():
        print(f"No existe {TRADES}")
        return

    trades = pd.read_csv(TRADES)

    if trades.empty:
        print("paper_trades.csv está vacío.")
        return

    closed = trades[trades["status"].astype(str).eq("CLOSED")].copy()

    if closed.empty:
        print("No hay trades cerrados.")
        return

    print(f"Trades cerrados: {len(closed)}")

    if "close_reason" in closed.columns:
        print("\n=== CIERRES POR RAZÓN ===")
        print(closed["close_reason"].fillna("").replace("", "UNKNOWN").value_counts().to_string())

    if not JOURNAL.exists():
        print(f"\nNo existe {JOURNAL}; no puedo reconstruir alineación previa.")
        return

    journal = pd.read_csv(JOURNAL)

    if journal.empty:
        print("candidate_journal.csv vacío.")
        return

    journal = journal.copy()
    journal["observed_at_dt"] = pd.to_datetime(journal["observed_at"], errors="coerce", utc=True)
    journal = journal.dropna(subset=["observed_at_dt"])

    for col in ["best_bid", "best_ask", "spread", "score", "fair_edge_to_ask"]:
        if col in journal.columns:
            journal[col] = pd.to_numeric(journal[col], errors="coerce")

    audit_rows = []

    for _, trade in closed.iterrows():
        close_reason = safe_str(trade.get("close_reason"))

        opened_at = pd.to_datetime(trade.get("opened_at"), errors="coerce", utc=True)
        closed_at = pd.to_datetime(trade.get("closed_at"), errors="coerce", utc=True)

        if pd.isna(opened_at) or pd.isna(closed_at):
            continue

        question = safe_str(trade.get("question"))
        outcome = safe_str(trade.get("outcome"))
        symbol = safe_str(trade.get("crypto_symbol")).strip().upper()

        mask = (
            journal["question"].astype(str).eq(question)
            & journal["outcome"].astype(str).eq(outcome)
            & journal["crypto_symbol"].astype(str).str.upper().eq(symbol)
            & (journal["observed_at_dt"] >= opened_at)
            & (journal["observed_at_dt"] <= closed_at)
        )

        rows = journal[mask].sort_values("observed_at_dt").copy()

        if rows.empty:
            audit_rows.append(
                {
                    "crypto_symbol": symbol,
                    "outcome": outcome,
                    "close_reason": close_reason,
                    "entry_price": trade.get("entry_price"),
                    "current_bid": trade.get("current_bid"),
                    "pnl_pct": trade.get("pnl_pct"),
                    "journal_points": 0,
                    "not_aligned_points": 0,
                    "aligned_points": 0,
                    "conflict_points": 0,
                    "last_alignment": "",
                    "last_binance_bias": "",
                    "last_crypto_decision": "",
                    "minutes_open": (closed_at - opened_at).total_seconds() / 60,
                    "question": question,
                }
            )
            continue

        alignments = rows["crypto_alignment"].fillna("").astype(str).str.upper()
        decisions = rows["crypto_decision"].fillna("").astype(str)
        binance_bias = rows["binance_bias"].fillna("").astype(str)

        not_aligned_points = int((alignments == "NEUTRAL").sum())
        aligned_points = int((alignments == "ALIGNED").sum())
        conflict_points = int((alignments == "CONFLICT").sum())

        last = rows.iloc[-1]

        audit_rows.append(
            {
                "crypto_symbol": symbol,
                "outcome": outcome,
                "close_reason": close_reason,
                "entry_price": trade.get("entry_price"),
                "current_bid": trade.get("current_bid"),
                "pnl_pct": trade.get("pnl_pct"),
                "journal_points": len(rows),
                "not_aligned_points": not_aligned_points,
                "aligned_points": aligned_points,
                "conflict_points": conflict_points,
                "last_alignment": safe_str(last.get("crypto_alignment")),
                "last_binance_bias": safe_str(last.get("binance_bias")),
                "last_crypto_decision": safe_str(last.get("crypto_decision")),
                "last_best_bid": last.get("best_bid"),
                "last_best_ask": last.get("best_ask"),
                "last_score": last.get("score"),
                "last_fair_edge_to_ask": last.get("fair_edge_to_ask"),
                "minutes_open": (closed_at - opened_at).total_seconds() / 60,
                "question": question,
            }
        )

    audit = pd.DataFrame(audit_rows)

    if audit.empty:
        print("No se pudo auditar ningún cierre.")
        return

    out = Path("data/paper_exit_audit.csv")
    audit.to_csv(out, index=False)

    print(f"\nArchivo: {out}")

    cols = [
        "crypto_symbol",
        "outcome",
        "close_reason",
        "entry_price",
        "current_bid",
        "pnl_pct",
        "minutes_open",
        "journal_points",
        "not_aligned_points",
        "aligned_points",
        "conflict_points",
        "last_alignment",
        "last_binance_bias",
        "last_crypto_decision",
        "question",
    ]

    cols = [col for col in cols if col in audit.columns]

    print("\n=== AUDITORÍA DE CIERRES ===")
    print(audit[cols].to_string(index=False))

    risky = audit[audit["close_reason"].astype(str).eq("RISK_EXIT_BINANCE_NOT_ALIGNED")]

    if not risky.empty:
        print("\n=== SOLO RISK_EXIT_BINANCE_NOT_ALIGNED ===")
        print(risky[cols].to_string(index=False))


if __name__ == "__main__":
    main()
