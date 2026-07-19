from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


DEFAULT_PATH = "data/crypto_signal_snapshot_fair_value.csv"


def print_binance_state(df: pd.DataFrame) -> None:
    print("\n=== BINANCE MARKET STATE ===")

    cols = [
        "crypto_symbol",
        "binance_spot_price",
        "binance_bias",
        "binance_momentum_5m_pct",
        "binance_momentum_15m_pct",
        "binance_window_pct",
        "binance_bias_score",
    ]

    existing = [c for c in cols if c in df.columns]

    if "crypto_symbol" not in df.columns or not existing:
        print("No hay columnas Binance en el snapshot actual.")
        return

    state = (
        df[existing]
        .drop_duplicates(subset=["crypto_symbol"])
        .sort_values("crypto_symbol")
    )

    print(state.to_string(index=False))


def print_decisions(df: pd.DataFrame) -> None:
    print("\n=== DECISIONES ===")

    if "crypto_decision" not in df.columns:
        print("No existe crypto_decision.")
        return

    print(df["crypto_decision"].value_counts(dropna=False).to_string())


def print_buy_watch(df: pd.DataFrame) -> None:
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
        "flow_bias",
        "crypto_decision",
        "crypto_decision_reasons",
    ]

    cols = [c for c in cols if c in df.columns]

    if ops.empty:
        print("No hay oportunidades BUY/WATCH reales ahora.")
        return

    sort_col = "fair_edge_to_ask" if "fair_edge_to_ask" in ops.columns else cols[0]

    print(
        ops.sort_values(sort_col, ascending=False, na_position="last")[cols]
        .to_string(index=False)
    )


def print_discard_reasons(df: pd.DataFrame) -> None:
    print("\n=== TOP RAZONES DE DESCARTE ===")

    if "crypto_decision_reasons" not in df.columns:
        print("No existe crypto_decision_reasons.")
        return

    print(df["crypto_decision_reasons"].value_counts(dropna=False).head(20).to_string())


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)

    if not path.exists():
        raise SystemExit(f"No existe el archivo: {path}")

    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        raise SystemExit(f"Archivo vacío: {path}")

    print_binance_state(df)
    print_decisions(df)
    print_buy_watch(df)
    print_discard_reasons(df)

    print("\n=== RESUMEN ===")
    print(f"Filas totales: {len(df)}")

    if "crypto_decision" in df.columns:
        ops = df[df["crypto_decision"].isin(["CRYPTO_BUY_FAIR_EDGE", "CRYPTO_WATCH_FAIR_EDGE"])]
        print(f"Oportunidades BUY/WATCH: {len(ops)}")
    else:
        print("Oportunidades BUY/WATCH: N/A")


if __name__ == "__main__":
    main()
