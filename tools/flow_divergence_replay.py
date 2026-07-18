from __future__ import annotations

from pathlib import Path
import os

import pandas as pd


JOURNAL = Path(os.getenv("CANDIDATE_JOURNAL_PATH", "data/candidate_journal.csv"))
OUT = Path(os.getenv("FLOW_DIVERGENCE_OUT", "data/flow_divergence_replay.csv"))
SUMMARY_OUT = Path(os.getenv("FLOW_DIVERGENCE_SUMMARY_OUT", "data/flow_divergence_summary.csv"))

LOOKBACK_HOURS = float(os.getenv("FLOW_REPLAY_LOOKBACK_HOURS", "6"))
HORIZONS = [
    int(x.strip())
    for x in os.getenv("FLOW_REPLAY_HORIZONS", "30,60,120,180").split(",")
    if x.strip()
]
CONFIRMATION_WINDOW_MINUTES = int(os.getenv("FLOW_CONFIRMATION_WINDOW_MINUTES", "10"))


def safe_str(value) -> str:
    if value is None:
        return ""

    text = str(value)

    if text.lower() == "nan":
        return ""

    return text


def safe_float(value, default=None):
    try:
        if value is None:
            return default

        text = str(value).strip()

        if text == "" or text.lower() == "nan":
            return default

        return float(text)
    except Exception:
        return default


def signal_key(row: pd.Series) -> str:
    token_id = safe_str(row.get("token_id")).strip()

    if token_id:
        return f"TOKEN:{token_id}"

    return "|".join(
        [
            safe_str(row.get("crypto_symbol")).strip(),
            safe_str(row.get("outcome")).strip(),
            safe_str(row.get("question")).strip(),
        ]
    )


def flow_state(alignment: str, flow: str) -> str:
    alignment = safe_str(alignment).upper()
    flow = safe_str(flow).upper()

    if alignment == "ALIGNED" and flow == "BULLISH":
        return "ALIGNED_FLOW_BULLISH"

    if alignment == "ALIGNED" and flow == "BEARISH":
        return "ALIGNED_FLOW_BEARISH"

    if alignment == "ALIGNED" and flow == "NEUTRAL":
        return "ALIGNED_FLOW_NEUTRAL"

    if alignment == "CONFLICT":
        return "CONFLICT"

    if alignment == "NEUTRAL":
        return "NEUTRAL"

    return "UNKNOWN"


def load_journal() -> pd.DataFrame:
    if not JOURNAL.exists():
        raise FileNotFoundError(f"No existe {JOURNAL}")

    df = pd.read_csv(JOURNAL)

    if df.empty:
        return df

    df["observed_at"] = pd.to_datetime(df["observed_at"], errors="coerce", utc=True)
    df = df.dropna(subset=["observed_at"]).copy()

    for col in [
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_edge_to_ask",
        "distance_pct",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["signal_key"] = df.apply(signal_key, axis=1)

    return df.sort_values("observed_at").reset_index(drop=True)


def replay_signal(entry: pd.Series, history: pd.DataFrame, horizon_minutes: int) -> dict:
    entry_time = entry["observed_at"]
    entry_ask = safe_float(entry.get("best_ask"))
    entry_bid = safe_float(entry.get("best_bid"))

    base = {
        "entry_time": entry_time,
        "horizon_minutes": horizon_minutes,
        "signal_key": entry.get("signal_key"),
        "crypto_symbol": entry.get("crypto_symbol"),
        "outcome": entry.get("outcome"),
        "question": entry.get("question"),
        "crypto_decision": entry.get("crypto_decision"),
        "crypto_alignment": safe_str(entry.get("crypto_alignment")).upper(),
        "flow_bias": safe_str(entry.get("flow_bias")).upper(),
        "flow_state": flow_state(entry.get("crypto_alignment"), entry.get("flow_bias")),
        "entry_bid": entry_bid,
        "entry_ask": entry_ask,
        "spread": safe_float(entry.get("spread")),
        "score": safe_float(entry.get("score")),
        "fair_edge_to_ask": safe_float(entry.get("fair_edge_to_ask")),
        "distance_pct": safe_float(entry.get("distance_pct")),
        "confirmation_count_10m": None,
        "exit_time": None,
        "exit_bid": None,
        "max_bid": None,
        "min_bid": None,
        "pnl_pct_exit": None,
        "pnl_pct_max": None,
        "pnl_pct_min": None,
        "status": "UNKNOWN",
    }

    if entry_ask is None or entry_ask <= 0:
        base["status"] = "INVALID_ENTRY_ASK"
        return base

    same = history[history["signal_key"].eq(entry["signal_key"])].copy()

    confirm_start = entry_time - pd.Timedelta(minutes=CONFIRMATION_WINDOW_MINUTES)
    confirm_rows = same[
        (same["observed_at"] >= confirm_start)
        & (same["observed_at"] <= entry_time)
        & same["crypto_decision"].isin(["CRYPTO_BUY_FAIR_EDGE", "CRYPTO_WATCH_FAIR_EDGE"])
    ]

    base["confirmation_count_10m"] = len(confirm_rows)

    end_time = entry_time + pd.Timedelta(minutes=horizon_minutes)

    future = same[
        (same["observed_at"] > entry_time)
        & (same["observed_at"] <= end_time)
        & same["best_bid"].notna()
    ].copy()

    if future.empty:
        base["status"] = "NO_FUTURE_ROWS"
        return base

    exit_row = future.iloc[-1]
    exit_bid = safe_float(exit_row.get("best_bid"))
    max_bid = future["best_bid"].max()
    min_bid = future["best_bid"].min()

    base.update(
        {
            "exit_time": exit_row["observed_at"],
            "exit_bid": exit_bid,
            "max_bid": max_bid,
            "min_bid": min_bid,
            "pnl_pct_exit": ((exit_bid - entry_ask) / entry_ask) * 100 if exit_bid is not None else None,
            "pnl_pct_max": ((max_bid - entry_ask) / entry_ask) * 100 if pd.notna(max_bid) else None,
            "pnl_pct_min": ((min_bid - entry_ask) / entry_ask) * 100 if pd.notna(min_bid) else None,
            "status": "EVALUATED",
        }
    )

    return base


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    evaluated = results[results["status"].eq("EVALUATED")].copy()

    if evaluated.empty:
        return pd.DataFrame()

    rows = []

    group_cols = [
        "horizon_minutes",
        "crypto_symbol",
        "crypto_alignment",
        "flow_bias",
        "flow_state",
    ]

    for key, g in evaluated.groupby(group_cols, dropna=False):
        item = dict(zip(group_cols, key))

        item.update(
            {
                "observations": len(g),
                "unique_signals": g["signal_key"].nunique(),
                "avg_pnl_pct_exit": g["pnl_pct_exit"].mean(),
                "median_pnl_pct_exit": g["pnl_pct_exit"].median(),
                "win_rate_exit_pct": (g["pnl_pct_exit"] > 0).mean() * 100,
                "avg_pnl_pct_max": g["pnl_pct_max"].mean(),
                "avg_pnl_pct_min": g["pnl_pct_min"].mean(),
                "avg_edge": g["fair_edge_to_ask"].mean(),
                "max_edge": g["fair_edge_to_ask"].max(),
                "avg_score": g["score"].mean(),
                "avg_spread": g["spread"].mean(),
                "avg_confirmation_count_10m": g["confirmation_count_10m"].mean(),
            }
        )

        rows.append(item)

    return pd.DataFrame(rows).sort_values(
        ["horizon_minutes", "avg_pnl_pct_exit", "win_rate_exit_pct"],
        ascending=[True, False, False],
    )


def main() -> None:
    print("\n=== FLOW DIVERGENCE REPLAY ===")

    df = load_journal()

    if df.empty:
        print("candidate_journal.csv está vacío.")
        return

    end = df["observed_at"].max()
    start = end - pd.Timedelta(hours=LOOKBACK_HOURS)

    recent = df[(df["observed_at"] >= start) & (df["observed_at"] <= end)].copy()

    entries = recent[
        recent["crypto_decision"].isin(["CRYPTO_BUY_FAIR_EDGE", "CRYPTO_WATCH_FAIR_EDGE"])
    ].copy()

    print(f"Ventana entradas: {start} -> {end}")
    print(f"Filas recientes: {len(recent)}")
    print(f"Entradas BUY/WATCH observadas: {len(entries)}")

    if entries.empty:
        print("No hay BUY/WATCH para replay.")
        return

    rows = []

    for _, entry in entries.iterrows():
        for horizon in HORIZONS:
            rows.append(replay_signal(entry, df, horizon))

    results = pd.DataFrame(rows)
    summary = summarize(results)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(OUT, index=False)
    summary.to_csv(SUMMARY_OUT, index=False)

    print(f"Archivo detalle: {OUT}")
    print(f"Archivo resumen: {SUMMARY_OUT}")

    print("\n=== RESUMEN POR FLOW ===")
    if summary.empty:
        print("No hubo filas evaluables.")
    else:
        cols = [
            "horizon_minutes",
            "crypto_symbol",
            "crypto_alignment",
            "flow_bias",
            "flow_state",
            "observations",
            "unique_signals",
            "avg_pnl_pct_exit",
            "median_pnl_pct_exit",
            "win_rate_exit_pct",
            "avg_pnl_pct_max",
            "avg_pnl_pct_min",
            "avg_edge",
            "max_edge",
            "avg_score",
            "avg_spread",
            "avg_confirmation_count_10m",
        ]
        print(summary[cols].to_string(index=False))

    print("\n=== TOP 30 ENTRADAS EVALUADAS ===")
    evaluated = results[results["status"].eq("EVALUATED")].copy()

    if evaluated.empty:
        print(results["status"].value_counts().to_string())
    else:
        cols = [
            "entry_time",
            "horizon_minutes",
            "crypto_symbol",
            "outcome",
            "crypto_decision",
            "entry_ask",
            "exit_bid",
            "pnl_pct_exit",
            "pnl_pct_max",
            "pnl_pct_min",
            "fair_edge_to_ask",
            "score",
            "spread",
            "confirmation_count_10m",
            "crypto_alignment",
            "flow_bias",
            "flow_state",
            "question",
        ]

        print(
            evaluated.sort_values(["pnl_pct_exit", "fair_edge_to_ask"], ascending=[False, False])
            [cols]
            .head(30)
            .to_string(index=False)
        )


if __name__ == "__main__":
    main()
