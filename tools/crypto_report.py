from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


DEFAULT_PATH = "data/crypto_signal_snapshot_fair_value.csv"


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)

    if not path.exists():
        raise SystemExit(f"No existe el archivo: {path}")

    df = pd.read_csv(path)

    print("\n=== BINANCE MARKET STATE ===")

    binance_cols = [
        "crypto_symbol",
        "binance_spot_price",
        "binance_bias",
        "binance_momentum_5m_pct",
        "binance_momentum_15m_pct",
        "binance_momentum_full_window_pct",
    ]
    binance_cols = [c for c in binance_cols if c in df.columns]

    if binance_cols:
        market = (
            df[binance_cols]
            .drop_duplicates(subset=["crypto_symbol"])
            .sort_values("crypto_symbol")
        )
        print(market.to_string(index=False))
    else:
        print("No encontré columnas Binance en el CSV.")

    print("\n=== DECISIONES ===")
    if "crypto_decision" in df.columns:
        print(df["crypto_decision"].value_counts(dropna=False).to_string())
    else:
        print("No existe crypto_decision.")

    print("\n=== BUY / WATCH REALES ===")

    if "crypto_decision" not in df.columns:
        print("No existe crypto_decision.")
        return

    ops = df[df["crypto_decision"].isin(["CRYPTO_BUY_FAIR_EDGE", "CRYPTO_WATCH_FAIR_EDGE"])]

    cols = [
        "question",
        "outcome",
        "crypto_symbol",
        "crypto_alignment",
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "binance_spot_price",
        "threshold_price",
        "distance_to_threshold_pct",
        "fair_probability",
        "fair_edge_to_ask",
        "crypto_decision",
        "crypto_decision_reasons",
    ]
    cols = [c for c in cols if c in df.columns]

    if ops.empty:
        print("No hay oportunidades BUY/WATCH reales ahora.")
    else:
        print(
            ops.sort_values("fair_edge_to_ask", ascending=False, na_position="last")[cols]
            .to_string(index=False)
        )

    print("\n=== TOP RAZONES DE DESCARTE ===")
    if "crypto_decision_reasons" in df.columns:
        print(df["crypto_decision_reasons"].value_counts(dropna=False).head(20).to_string())
    else:
        print("No existe crypto_decision_reasons.")

    print("\n=== RESUMEN ===")
    print(f"Filas totales: {len(df)}")
    print(f"Oportunidades BUY/WATCH: {len(ops)}")


if __name__ == "__main__":
    main()
