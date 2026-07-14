from __future__ import annotations

from pathlib import Path
import pandas as pd


SNAPSHOT_PATH = Path("data/crypto_signal_snapshot_fair_value.csv")


def main() -> None:
    print("\n=== NEAR MISS REPORT ===")

    if not SNAPSHOT_PATH.exists():
        print(f"No existe {SNAPSHOT_PATH}")
        return

    try:
        df = pd.read_csv(SNAPSHOT_PATH)
    except pd.errors.EmptyDataError:
        print("Snapshot vacío.")
        return

    if df.empty:
        print("No hay filas.")
        return

    for col in [
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_probability",
        "fair_edge_to_ask",
        "distance_pct",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    print("Filas:", len(df))

    if "crypto_decision" in df.columns:
        print("\n=== DECISIONES ===")
        print(df["crypto_decision"].value_counts(dropna=False).to_string())

    if "crypto_alignment" in df.columns:
        print("\n=== ALIGNMENT ===")
        print(df["crypto_alignment"].value_counts(dropna=False).to_string())

    if "crypto_decision_reasons" in df.columns:
        print("\n=== TOP RAZONES ===")
        print(df["crypto_decision_reasons"].value_counts(dropna=False).head(20).to_string())

    candidates = df.copy()

    if "fair_edge_to_ask" in candidates.columns:
        candidates = candidates[candidates["fair_edge_to_ask"].notna()]
        candidates = candidates.sort_values(
            ["fair_edge_to_ask", "score"],
            ascending=[False, False],
            na_position="last",
        )

    print("\n=== TOP POR EDGE FAIR VALUE ===")
    cols = [
        "crypto_symbol",
        "outcome",
        "market_bias",
        "binance_bias",
        "crypto_alignment",
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_probability",
        "fair_edge_to_ask",
        "distance_pct",
        "crypto_decision",
        "crypto_decision_reasons",
        "question",
    ]
    cols = [c for c in cols if c in candidates.columns]

    if candidates.empty:
        print("No hay candidatos con fair_edge_to_ask.")
    else:
        print(candidates[cols].head(30).to_string(index=False))

    soft = df.copy()

    if "fair_edge_to_ask" in soft.columns:
        soft = soft[
            soft["fair_edge_to_ask"].notna()
            & (soft["fair_edge_to_ask"] > 0)
        ]

    if "best_ask" in soft.columns:
        soft = soft[soft["best_ask"].notna() & (soft["best_ask"] > 0) & (soft["best_ask"] < 0.75)]

    if "spread" in soft.columns:
        soft = soft[soft["spread"].notna() & (soft["spread"] <= 0.05)]

    if "score" in soft.columns:
        soft = soft[soft["score"].notna() & (soft["score"] >= 60)]

    if "crypto_alignment" in soft.columns:
        soft = soft[soft["crypto_alignment"].isin(["ALIGNED"])]

    soft = soft.sort_values(
        ["fair_edge_to_ask", "score", "spread"],
        ascending=[False, False, True],
        na_position="last",
    )

    print("\n=== CANDIDATOS QUE CASI PASAN FILTROS SUAVES ===")
    print("Reglas suaves: edge>0, ask<0.75, spread<=0.05, score>=60, ALIGNED")
    if soft.empty:
        print("No hay near-misses suaves.")
    else:
        print(soft[cols].head(30).to_string(index=False))


if __name__ == "__main__":
    main()
