from __future__ import annotations

from pathlib import Path
import os

import pandas as pd


JOURNAL = Path(os.getenv("CANDIDATE_JOURNAL_PATH", "data/candidate_journal.csv"))
OUT = Path(os.getenv("SYMBOL_COVERAGE_OUT", "data/symbol_coverage_report.csv"))
DECISION_OUT = Path(os.getenv("SYMBOL_DECISION_OUT", "data/symbol_decision_coverage.csv"))
REASONS_OUT = Path(os.getenv("SYMBOL_REASONS_OUT", "data/symbol_top_blockers.csv"))

LOOKBACK_HOURS = float(os.getenv("SYMBOL_COVERAGE_LOOKBACK_HOURS", "6"))


def numeric(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series([None] * len(df), index=df.index)

    return pd.to_numeric(df[col], errors="coerce")


def contains(series: pd.Series, pattern: str) -> pd.Series:
    return series.fillna("").astype(str).str.contains(pattern, case=False, regex=True)


def main() -> None:
    print("\n=== SYMBOL COVERAGE REPORT ===")

    if not JOURNAL.exists():
        raise FileNotFoundError(f"No existe {JOURNAL}")

    df = pd.read_csv(JOURNAL)

    if df.empty:
        print("candidate_journal.csv está vacío.")
        return

    df["observed_at"] = pd.to_datetime(df["observed_at"], errors="coerce", utc=True)
    df = df.dropna(subset=["observed_at"])

    end = df["observed_at"].max()
    start = end - pd.Timedelta(hours=LOOKBACK_HOURS)

    recent = df[(df["observed_at"] >= start) & (df["observed_at"] <= end)].copy()

    if recent.empty:
        print("No hay datos recientes para analizar.")
        return

    for col in [
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_edge_to_ask",
        "bid_size",
        "ask_size",
        "distance_pct",
    ]:
        if col in recent.columns:
            recent[col] = pd.to_numeric(recent[col], errors="coerce")

    recent["crypto_symbol"] = recent.get("crypto_symbol", "UNKNOWN").fillna("UNKNOWN").astype(str)
    recent["crypto_decision"] = recent.get("crypto_decision", "").fillna("").astype(str)
    recent["crypto_alignment"] = recent.get("crypto_alignment", "").fillna("").astype(str).str.upper()
    recent["reasons"] = recent.get("crypto_decision_reasons", "").fillna("").astype(str)

    buy_watch_mask = recent["crypto_decision"].isin(
        ["CRYPTO_BUY_FAIR_EDGE", "CRYPTO_WATCH_FAIR_EDGE"]
    )

    rows = []

    for symbol, g in recent.groupby("crypto_symbol", dropna=False):
        reasons = g["reasons"]
        decision = g["crypto_decision"]

        rows.append(
            {
                "crypto_symbol": symbol,
                "rows": len(g),
                "unique_questions": g["question"].nunique() if "question" in g.columns else None,
                "buy_watch": int(decision.isin(["CRYPTO_BUY_FAIR_EDGE", "CRYPTO_WATCH_FAIR_EDGE"]).sum()),
                "buy": int((decision == "CRYPTO_BUY_FAIR_EDGE").sum()),
                "watch": int((decision == "CRYPTO_WATCH_FAIR_EDGE").sum()),
                "buy_watch_rate_pct": decision.isin(["CRYPTO_BUY_FAIR_EDGE", "CRYPTO_WATCH_FAIR_EDGE"]).mean() * 100,
                "aligned_rate_pct": (g["crypto_alignment"] == "ALIGNED").mean() * 100,
                "conflict_rate_pct": (g["crypto_alignment"] == "CONFLICT").mean() * 100,
                "neutral_rate_pct": (g["crypto_alignment"] == "NEUTRAL").mean() * 100,
                "incomplete_orderbook_rate_pct": (
                    contains(reasons, "INCOMPLETE_ORDERBOOK").mean() * 100
                ),
                "threshold_too_far_rate_pct": (
                    contains(reasons, "THRESHOLD_TOO_FAR").mean() * 100
                ),
                "binance_not_aligned_rate_pct": (
                    contains(reasons, "BINANCE_NOT_ALIGNED").mean() * 100
                ),
                "binance_conflict_rate_pct": (
                    contains(reasons, "BINANCE_CONFLICT").mean() * 100
                ),
                "spread_too_high_rate_pct": (
                    contains(reasons, "REL_SPREAD_TOO_HIGH|SPREAD_TOO_WIDE").mean() * 100
                ),
                "score_low_rate_pct": (
                    contains(reasons, "PM_SCORE_LOW").mean() * 100
                ),
                "edge_low_or_missing_rate_pct": (
                    contains(reasons, "PM_EDGE_LOW_OR_MISSING").mean() * 100
                ),
                "liquidity_issue_rate_pct": (
                    contains(reasons, "NO_TOP_LIQUIDITY|LOW_TOP_LIQUIDITY|INCOMPLETE_ORDERBOOK").mean() * 100
                ),
                "avg_score": numeric(g, "score").mean(),
                "max_score": numeric(g, "score").max(),
                "avg_edge": numeric(g, "fair_edge_to_ask").mean(),
                "max_edge": numeric(g, "fair_edge_to_ask").max(),
                "avg_spread": numeric(g, "spread").mean(),
                "median_spread": numeric(g, "spread").median(),
                "avg_ask": numeric(g, "best_ask").mean(),
                "min_ask": numeric(g, "best_ask").min(),
                "max_bid": numeric(g, "best_bid").max(),
            }
        )

    summary = pd.DataFrame(rows).sort_values(
        ["buy_watch", "max_edge", "avg_score"], ascending=[False, False, False]
    )

    decision_table = pd.crosstab(recent["crypto_symbol"], recent["crypto_decision"])

    reason_rows = []

    for symbol, g in recent.groupby("crypto_symbol", dropna=False):
        top_reasons = g["reasons"].value_counts().head(10)

        for reason, count in top_reasons.items():
            reason_rows.append(
                {
                    "crypto_symbol": symbol,
                    "count": int(count),
                    "rate_pct": count / len(g) * 100,
                    "reason": reason,
                }
            )

    blockers = pd.DataFrame(reason_rows)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT, index=False)
    decision_table.to_csv(DECISION_OUT)
    blockers.to_csv(REASONS_OUT, index=False)

    print(f"Ventana: {start} -> {end}")
    print(f"Filas recientes: {len(recent)}")
    print(f"BUY/WATCH recientes: {int(buy_watch_mask.sum())}")
    print(f"Archivo resumen: {OUT}")
    print(f"Archivo decisiones: {DECISION_OUT}")
    print(f"Archivo blockers: {REASONS_OUT}")

    print("\n=== COBERTURA POR SÍMBOLO ===")
    cols = [
        "crypto_symbol",
        "rows",
        "unique_questions",
        "buy_watch",
        "buy",
        "watch",
        "buy_watch_rate_pct",
        "aligned_rate_pct",
        "conflict_rate_pct",
        "neutral_rate_pct",
        "incomplete_orderbook_rate_pct",
        "threshold_too_far_rate_pct",
        "binance_conflict_rate_pct",
        "spread_too_high_rate_pct",
        "score_low_rate_pct",
        "edge_low_or_missing_rate_pct",
        "liquidity_issue_rate_pct",
        "avg_score",
        "max_score",
        "avg_edge",
        "max_edge",
        "avg_spread",
        "min_ask",
        "max_bid",
    ]

    print(summary[cols].to_string(index=False))

    print("\n=== DECISIONES POR SÍMBOLO ===")
    print(decision_table.to_string())

    print("\n=== TOP BLOCKERS POR SÍMBOLO ===")
    print(blockers.head(40).to_string(index=False))


if __name__ == "__main__":
    main()
