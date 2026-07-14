from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd


DEFAULT_PATH = "data/signal_journal.csv"


def safe_float(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)

    max_entry_ask = float(os.getenv("PAPER_MAX_ENTRY_ASK", "0.60"))
    max_entry_spread = float(os.getenv("PAPER_MAX_ENTRY_SPREAD", "0.02"))
    min_entry_fair_edge = float(os.getenv("PAPER_MIN_ENTRY_FAIR_EDGE", "0.25"))
    min_entry_score = float(os.getenv("PAPER_MIN_ENTRY_SCORE", "80"))

    if not path.exists():
        print(f"No existe signal journal: {path}")
        return

    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        print("signal_journal.csv está vacío.")
        return

    if df.empty:
        print("No hay señales registradas todavía.")
        return

    numeric_cols = [
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "binance_spot_price",
        "threshold_price",
        "distance_to_threshold_pct",
        "fair_probability",
        "fair_edge_to_ask",
        "paper_entry_price",
        "paper_current_bid",
        "paper_pnl_usd",
        "paper_pnl_pct",
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    def entry_block_reason(row: pd.Series) -> str:
        reasons = []

        ask = safe_float(row.get("best_ask"))
        spread = safe_float(row.get("spread"))
        edge = safe_float(row.get("fair_edge_to_ask"))
        score = safe_float(row.get("score"))

        if ask is None:
            reasons.append("NO_ASK")
        elif ask > max_entry_ask:
            reasons.append("ASK_TOO_HIGH")

        if spread is None:
            reasons.append("NO_SPREAD")
        elif spread > max_entry_spread:
            reasons.append("SPREAD_TOO_WIDE")

        if edge is None:
            reasons.append("NO_EDGE")
        elif edge < min_entry_fair_edge:
            reasons.append("EDGE_TOO_LOW")

        if score is None:
            reasons.append("NO_SCORE")
        elif score < min_entry_score:
            reasons.append("SCORE_TOO_LOW")

        return ",".join(reasons) if reasons else "PASS"

    df["entry_filter_result"] = df.apply(entry_block_reason, axis=1)

    if "observed_at" in df.columns:
        df["observed_at_dt"] = pd.to_datetime(df["observed_at"], utc=True, errors="coerce")

    print("\n=== SIGNAL PERFORMANCE REPORT ===")
    print(f"Señales registradas: {len(df)}")

    if "signal_key" in df.columns:
        print(f"Señales únicas: {df['signal_key'].nunique()}")

    if "crypto_decision" in df.columns:
        print("\n=== DECISIONES ===")
        print(df["crypto_decision"].fillna("UNKNOWN").value_counts().to_string())

    if "paper_status" in df.columns:
        print("\n=== ESTADO PAPER ===")
        print(df["paper_status"].fillna("UNKNOWN").value_counts().to_string())

    print("\n=== FILTROS DE ENTRADA ACTUALES ===")
    print(f"Ask máximo: {max_entry_ask}")
    print(f"Spread máximo: {max_entry_spread}")
    print(f"Edge mínimo: {min_entry_fair_edge}")
    print(f"Score mínimo: {min_entry_score}")

    print("\n=== RESULTADO DE FILTROS ===")
    print(df["entry_filter_result"].value_counts().to_string())

    passed = df[df["entry_filter_result"].eq("PASS")]
    print(f"\nSeñales que pasan filtros: {len(passed)}")

    print("\n=== TOP SEÑALES POR EDGE ===")
    cols = [
        "observed_at",
        "crypto_symbol",
        "outcome",
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_probability",
        "fair_edge_to_ask",
        "paper_status",
        "paper_close_reason",
        "entry_filter_result",
        "question",
    ]
    cols = [c for c in cols if c in df.columns]

    sort_col = "fair_edge_to_ask" if "fair_edge_to_ask" in df.columns else cols[0]
    print(
        df.sort_values(sort_col, ascending=False, na_position="last")
        .head(20)[cols]
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
