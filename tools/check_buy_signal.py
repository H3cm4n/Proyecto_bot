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

    if "crypto_decision" not in df.columns:
        raise SystemExit("El CSV no tiene columna crypto_decision.")

    buy = df[df["crypto_decision"].eq("CRYPTO_BUY_FAIR_EDGE")]

    if buy.empty:
        print("\nSin CRYPTO_BUY_FAIR_EDGE por ahora.")
        return

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
    cols = [c for c in cols if c in buy.columns]

    print("\n🚨 CRYPTO_BUY_FAIR_EDGE DETECTADO 🚨")
    print(f"Señales BUY: {len(buy)}")
    print(
        buy.sort_values("fair_edge_to_ask", ascending=False, na_position="last")[cols]
        .to_string(index=False)
    )

    # Código 2 para que un script externo pueda detectar alerta.
    raise SystemExit(2)


if __name__ == "__main__":
    main()
