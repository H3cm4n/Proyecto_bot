from __future__ import annotations

from pathlib import Path
import pandas as pd


JOURNAL_PATH = Path("data/candidate_journal.csv")


def main() -> None:
    if not JOURNAL_PATH.exists():
        raise SystemExit(f"No existe {JOURNAL_PATH}")

    df = pd.read_csv(JOURNAL_PATH)

    work = df.copy()
    work = work[work["crypto_symbol"].astype(str).str.upper() == "BTCUSDT"]
    work = work[work["outcome"].astype(str).str.lower() == "yes"]

    print("\n=== MICRO DIAGNOSTICS BTC YES ===")
    print(f"Filas BTC Yes: {len(work)}")

    print("\n=== DECISIONES ===")
    print(work["crypto_decision"].value_counts(dropna=False).head(20).to_string())

    print("\n=== FLOW ===")
    print(work["flow_bias"].value_counts(dropna=False).to_string())

    print("\n=== ALIGNMENT ===")
    print(work["crypto_alignment"].value_counts(dropna=False).to_string())

    print("\n=== MICRO FILTER FUNNEL ===")

    checks = [
        ("BTCUSDT Yes", work),
        ("decision BUY", work[work["crypto_decision"] == "CRYPTO_BUY_FAIR_EDGE"]),
        ("aligned", work[work["crypto_alignment"] == "ALIGNED"]),
        ("flow bullish", work[work["flow_bias"] == "BULLISH"]),
        ("edge >= 0.30", work[work["fair_edge_to_ask"] >= 0.30]),
        ("score >= 80", work[work["score"] >= 80]),
        ("spread <= 0.01", work[work["spread"] <= 0.01]),
        ("ask 0.50-0.60", work[(work["best_ask"] >= 0.50) & (work["best_ask"] <= 0.60)]),
    ]

    for name, part in checks:
        print(f"{name:20s}: {len(part)}")

    micro = work[
        (work["crypto_decision"] == "CRYPTO_BUY_FAIR_EDGE")
        & (work["crypto_alignment"] == "ALIGNED")
        & (work["flow_bias"] == "BULLISH")
        & (work["fair_edge_to_ask"] >= 0.30)
        & (work["score"] >= 80)
        & (work["spread"] <= 0.01)
        & (work["best_ask"] >= 0.50)
        & (work["best_ask"] <= 0.60)
    ].copy()

    print("\n=== MICRO SETUPS QUE SÍ PASAN FILTROS ===")
    print(f"Total histórico en journal: {len(micro)}")

    cols = [
        "observed_at",
        "question",
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_edge_to_ask",
        "binance_bias",
        "flow_bias",
        "crypto_alignment",
        "crypto_decision",
    ]

    cols = [c for c in cols if c in micro.columns]

    if micro.empty:
        print("No hay setups exactos en el journal con los filtros actuales.")
    else:
        print(
            micro.sort_values("observed_at")
            .tail(20)[cols]
            .to_string(index=False)
        )

    print("\n=== MEJORES CANDIDATOS POR EDGE ===")
    cols2 = [
        "observed_at",
        "question",
        "crypto_decision",
        "crypto_alignment",
        "binance_bias",
        "flow_bias",
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_edge_to_ask",
        "crypto_decision_reasons",
    ]
    cols2 = [c for c in cols2 if c in work.columns]

    ranked = work.dropna(subset=["fair_edge_to_ask"]).sort_values(
        "fair_edge_to_ask",
        ascending=False,
    )

    print(ranked.head(25)[cols2].to_string(index=False))


if __name__ == "__main__":
    main()
