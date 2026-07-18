from __future__ import annotations

from pathlib import Path
import os

import pandas as pd


DETAIL = Path(os.getenv("FLOW_DIVERGENCE_OUT", "data/flow_divergence_replay.csv"))
OUT = Path(os.getenv("EDGE_SWEEP_OUT", "data/edge_threshold_sweep.csv"))

EDGE_VALUES = [
    float(x.strip())
    for x in os.getenv("EDGE_SWEEP_EDGE_VALUES", "0.10,0.15,0.20,0.25,0.30,0.35").split(",")
    if x.strip()
]

SCORE_VALUES = [
    float(x.strip())
    for x in os.getenv("EDGE_SWEEP_SCORE_VALUES", "70,75,80,85,90").split(",")
    if x.strip()
]

SPREAD_VALUES = [
    float(x.strip())
    for x in os.getenv("EDGE_SWEEP_SPREAD_VALUES", "0.01,0.02").split(",")
    if x.strip()
]

CONFIRM_VALUES = [
    int(x.strip())
    for x in os.getenv("EDGE_SWEEP_CONFIRM_VALUES", "1,2,3").split(",")
    if x.strip()
]

ASK_MIN_VALUES = [
    float(x.strip())
    for x in os.getenv("EDGE_SWEEP_ASK_MIN_VALUES", "0.45,0.50").split(",")
    if x.strip()
]

ASK_MAX_VALUES = [
    float(x.strip())
    for x in os.getenv("EDGE_SWEEP_ASK_MAX_VALUES", "0.56,0.60").split(",")
    if x.strip()
]

FLOW_POLICIES = [
    x.strip().upper()
    for x in os.getenv(
        "EDGE_SWEEP_FLOW_POLICIES",
        "ANY,BULLISH_ONLY,NO_BEARISH,BEARISH_ONLY,ALIGNED_BEARISH_ONLY,ALIGNED_BULLISH_ONLY",
    ).split(",")
    if x.strip()
]

MIN_OBSERVATIONS = int(os.getenv("EDGE_SWEEP_MIN_OBSERVATIONS", "5"))
MIN_UNIQUE_SIGNALS = int(os.getenv("EDGE_SWEEP_MIN_UNIQUE_SIGNALS", "1"))


def apply_flow_policy(df: pd.DataFrame, policy: str) -> pd.DataFrame:
    flow = df["flow_bias"].fillna("").astype(str).str.upper()
    state = df["flow_state"].fillna("").astype(str).str.upper()

    if policy == "ANY":
        return df

    if policy == "BULLISH_ONLY":
        return df[flow.eq("BULLISH")]

    if policy == "NO_BEARISH":
        return df[~flow.eq("BEARISH")]

    if policy == "BEARISH_ONLY":
        return df[flow.eq("BEARISH")]

    if policy == "ALIGNED_BEARISH_ONLY":
        return df[state.eq("ALIGNED_FLOW_BEARISH")]

    if policy == "ALIGNED_BULLISH_ONLY":
        return df[state.eq("ALIGNED_FLOW_BULLISH")]

    return df


def main() -> None:
    print("\n=== EDGE THRESHOLD SWEEP ===")

    if not DETAIL.exists():
        raise FileNotFoundError(
            f"No existe {DETAIL}. Corre primero: python tools/flow_divergence_replay.py"
        )

    df = pd.read_csv(DETAIL)

    if df.empty:
        print("flow_divergence_replay.csv está vacío.")
        return

    df = df[df["status"].eq("EVALUATED")].copy()

    if df.empty:
        print("No hay filas evaluadas para sweep.")
        return

    for col in [
        "entry_ask",
        "spread",
        "score",
        "fair_edge_to_ask",
        "confirmation_count_10m",
        "pnl_pct_exit",
        "pnl_pct_max",
        "pnl_pct_min",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    rows = []

    horizons = sorted(df["horizon_minutes"].dropna().unique().tolist())

    for horizon in horizons:
        hdf = df[df["horizon_minutes"].eq(horizon)].copy()

        for min_edge in EDGE_VALUES:
            for min_score in SCORE_VALUES:
                for max_spread in SPREAD_VALUES:
                    for min_confirm in CONFIRM_VALUES:
                        for ask_min in ASK_MIN_VALUES:
                            for ask_max in ASK_MAX_VALUES:
                                if ask_min > ask_max:
                                    continue

                                base = hdf[
                                    (hdf["fair_edge_to_ask"] >= min_edge)
                                    & (hdf["score"] >= min_score)
                                    & (hdf["spread"] <= max_spread)
                                    & (hdf["confirmation_count_10m"] >= min_confirm)
                                    & (hdf["entry_ask"] >= ask_min)
                                    & (hdf["entry_ask"] <= ask_max)
                                ].copy()

                                if base.empty:
                                    continue

                                for policy in FLOW_POLICIES:
                                    g = apply_flow_policy(base, policy)

                                    if g.empty:
                                        continue

                                    observations = len(g)
                                    unique_signals = g["signal_key"].nunique()

                                    qualified = (
                                        observations >= MIN_OBSERVATIONS
                                        and unique_signals >= MIN_UNIQUE_SIGNALS
                                    )

                                    rows.append(
                                        {
                                            "qualified": qualified,
                                            "horizon_minutes": horizon,
                                            "flow_policy": policy,
                                            "observations": observations,
                                            "unique_signals": unique_signals,
                                            "avg_pnl_pct_exit": g["pnl_pct_exit"].mean(),
                                            "median_pnl_pct_exit": g["pnl_pct_exit"].median(),
                                            "win_rate_exit_pct": (g["pnl_pct_exit"] > 0).mean() * 100,
                                            "avg_pnl_pct_max": g["pnl_pct_max"].mean(),
                                            "avg_pnl_pct_min": g["pnl_pct_min"].mean(),
                                            "worst_pnl_pct_exit": g["pnl_pct_exit"].min(),
                                            "best_pnl_pct_exit": g["pnl_pct_exit"].max(),
                                            "avg_edge": g["fair_edge_to_ask"].mean(),
                                            "max_edge": g["fair_edge_to_ask"].max(),
                                            "avg_score": g["score"].mean(),
                                            "avg_spread": g["spread"].mean(),
                                            "avg_entry_ask": g["entry_ask"].mean(),
                                            "min_edge": min_edge,
                                            "min_score": min_score,
                                            "max_spread": max_spread,
                                            "min_confirmations_10m": min_confirm,
                                            "ask_min": ask_min,
                                            "ask_max": ask_max,
                                        }
                                    )

    result = pd.DataFrame(rows)

    OUT.parent.mkdir(parents=True, exist_ok=True)

    if result.empty:
        print("No hubo combinaciones con resultados.")
        result.to_csv(OUT, index=False)
        return

    result = result.sort_values(
        [
            "qualified",
            "avg_pnl_pct_exit",
            "median_pnl_pct_exit",
            "win_rate_exit_pct",
            "observations",
        ],
        ascending=[False, False, False, False, False],
    )

    result.to_csv(OUT, index=False)

    print(f"Archivo sweep: {OUT}")
    print(f"Filas sweep: {len(result)}")
    print(f"Qualified mínimo obs={MIN_OBSERVATIONS}, unique={MIN_UNIQUE_SIGNALS}")

    cols = [
        "qualified",
        "horizon_minutes",
        "flow_policy",
        "observations",
        "unique_signals",
        "avg_pnl_pct_exit",
        "median_pnl_pct_exit",
        "win_rate_exit_pct",
        "worst_pnl_pct_exit",
        "best_pnl_pct_exit",
        "avg_pnl_pct_max",
        "avg_pnl_pct_min",
        "avg_edge",
        "max_edge",
        "avg_score",
        "avg_spread",
        "avg_entry_ask",
        "min_edge",
        "min_score",
        "max_spread",
        "min_confirmations_10m",
        "ask_min",
        "ask_max",
    ]

    print("\n=== TOP EDGE POLICIES ===")
    print(result[cols].head(40).to_string(index=False))

    print("\n=== TOP QUALIFIED ONLY ===")
    qualified = result[result["qualified"]]

    if qualified.empty:
        print("No hubo políticas calificadas con los mínimos actuales.")
    else:
        print(qualified[cols].head(40).to_string(index=False))


if __name__ == "__main__":
    main()
