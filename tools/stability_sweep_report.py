from __future__ import annotations

from pathlib import Path
import importlib.util
import itertools
import os
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
CSR_PATH = ROOT / "tools" / "candidate_stability_report.py"
JOURNAL = Path(os.getenv("CANDIDATE_JOURNAL_PATH", "data/candidate_journal.csv"))
OUT = Path(os.getenv("STABILITY_SWEEP_OUT", "data/stability_sweep_summary.csv"))
TOP_REPLAY_OUT = Path(os.getenv("STABILITY_SWEEP_TOP_REPLAY_OUT", "data/stability_sweep_top_replay.csv"))


def load_candidate_stability_module():
    spec = importlib.util.spec_from_file_location("candidate_stability_report", CSR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No pude cargar {CSR_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_semicolon(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(";") if item.strip()]


def parse_float_csv(name: str, default: str) -> list[float]:
    values = []
    for item in parse_csv(name, default):
        try:
            values.append(float(item))
        except ValueError:
            pass
    return values


def parse_int_csv(name: str, default: str) -> list[int]:
    values = []
    for item in parse_csv(name, default):
        try:
            values.append(int(item))
        except ValueError:
            pass
    return values


def parse_ranges(name: str, default: str) -> list[tuple[float, float]]:
    ranges = []

    for item in parse_csv(name, default):
        if ":" not in item:
            continue

        left, right = item.split(":", 1)

        try:
            ranges.append((float(left), float(right)))
        except ValueError:
            continue

    return ranges


def parse_score_ranges(name: str, default: str) -> list[tuple[float, str]]:
    ranges = []

    for item in parse_csv(name, default):
        if ":" not in item:
            continue

        left, right = item.split(":", 1)

        try:
            score_min = float(left)
        except ValueError:
            continue

        score_max = right.strip()
        ranges.append((score_min, score_max))

    return ranges


def prepare_journal(csr) -> pd.DataFrame:
    if not JOURNAL.exists():
        raise FileNotFoundError(f"No existe {JOURNAL}")

    df = pd.read_csv(JOURNAL)

    if df.empty:
        return df

    df = df.copy()

    if "signal_key" not in df.columns:
        df["signal_key"] = df.apply(csr.candidate_key, axis=1)
    else:
        df["signal_key"] = df["signal_key"].fillna("").astype(str)
        missing_key = df["signal_key"].str.strip().eq("")
        df.loc[missing_key, "signal_key"] = df[missing_key].apply(csr.candidate_key, axis=1)

    df["observed_at_dt"] = pd.to_datetime(df["observed_at"], errors="coerce", utc=True)
    df = df.dropna(subset=["observed_at_dt"])

    for col in [
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_probability",
        "fair_edge_to_ask",
        "distance_pct",
        "depth_imbalance",
        "threshold_price",
        "binance_spot_price",
    ]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


def set_env_config(
    decisions: str,
    ask_min: float,
    ask_max: float,
    spread_max: float,
    score_min: float,
    score_max: str,
    min_obs: int,
    lookback: int,
    max_gap: float,
    drawdown: float,
    tp: float,
    sl: float,
) -> None:
    os.environ["STABILITY_ALLOWED_DECISIONS"] = decisions
    os.environ["STABILITY_ASK_MIN"] = str(ask_min)
    os.environ["STABILITY_ASK_MAX"] = str(ask_max)
    os.environ["STABILITY_SPREAD_MAX"] = str(spread_max)
    os.environ["STABILITY_SCORE_MIN"] = str(score_min)
    os.environ["STABILITY_SCORE_MAX"] = score_max
    os.environ["STABILITY_MIN_OBSERVATIONS"] = str(min_obs)
    os.environ["STABILITY_LOOKBACK_MINUTES"] = str(lookback)
    os.environ["STABILITY_MAX_GAP_MINUTES"] = str(max_gap)
    os.environ["STABILITY_MAX_BID_DRAWDOWN_PCT"] = str(drawdown)
    os.environ["STABILITY_REPLAY_HORIZON_MINUTES"] = os.getenv("STABILITY_SWEEP_HORIZON_MINUTES", "60")
    os.environ["STABILITY_TAKE_PROFIT"] = str(tp)
    os.environ["STABILITY_STOP_LOSS"] = str(sl)


def base_and_events(csr, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    work = df.copy()

    base_results = work.apply(csr.classify_base_candidate, axis=1)
    work["_base_pass"] = base_results.apply(lambda item: item[0])
    work["_base_failures"] = base_results.apply(lambda item: ",".join(item[1]))

    events = csr.build_stable_events(work)
    return work, events


def summarize_result(
    replay: pd.DataFrame,
    events: pd.DataFrame,
    decisions: str,
    ask_min: float,
    ask_max: float,
    spread_max: float,
    score_min: float,
    score_max: str,
    min_obs: int,
    lookback: int,
    max_gap: float,
    drawdown: float,
    tp: float,
    sl: float,
) -> dict:
    return {
        "decisions": decisions,
        "ask_min": ask_min,
        "ask_max": ask_max,
        "spread_max": spread_max,
        "score_min": score_min,
        "score_max": score_max if score_max != "" else "None",
        "min_observations": min_obs,
        "lookback_minutes": lookback,
        "max_gap_minutes": max_gap,
        "max_bid_drawdown_pct": drawdown,
        "take_profit": tp,
        "stop_loss": sl,
        "stable_events": len(events),
        "unique_stable_signals": events["signal_key"].nunique() if not events.empty and "signal_key" in events.columns else 0,
        "replay_events": len(replay),
        "win_rate_exit": (replay["exit_pnl_pct"] > 0).mean() * 100,
        "avg_exit_pnl_pct": replay["exit_pnl_pct"].mean(),
        "median_exit_pnl_pct": replay["exit_pnl_pct"].median(),
        "avg_max_pnl_pct": replay["max_pnl_pct"].mean(),
        "worst_min_pnl_pct": replay["min_pnl_pct"].min(),
        "hit_tp_rate": replay["hit_take_profit"].mean() * 100,
        "hit_sl_rate": replay["hit_stop_loss"].mean() * 100,
    }


def main() -> None:
    print("\n=== STABILITY SWEEP REPORT ===")

    csr = load_candidate_stability_module()
    df = prepare_journal(csr)

    if df.empty:
        print("candidate_journal.csv está vacío.")
        return

    decision_sets = parse_semicolon(
        "STABILITY_SWEEP_DECISION_SETS",
        "CRYPTO_WAIT_BINANCE_NOT_ALIGNED;"
        "CRYPTO_IGNORE_ASK_TOO_LOW;"
        "CRYPTO_WAIT_BINANCE_NOT_ALIGNED,CRYPTO_IGNORE_ASK_TOO_LOW",
    )
    ask_ranges = parse_ranges(
        "STABILITY_SWEEP_ASK_RANGES",
        "0.065:0.080,0.070:0.080,0.060:0.100",
    )
    spread_max_values = parse_float_csv("STABILITY_SWEEP_SPREAD_MAX_VALUES", "0.001")
    score_ranges = parse_score_ranges(
        "STABILITY_SWEEP_SCORE_RANGES",
        "60:65,60:70,60:75,65:75",
    )
    min_obs_values = parse_int_csv("STABILITY_SWEEP_MIN_OBSERVATIONS_VALUES", "2,3")
    lookback_values = parse_int_csv("STABILITY_SWEEP_LOOKBACK_VALUES", "15")
    max_gap_values = parse_float_csv("STABILITY_SWEEP_MAX_GAP_VALUES", "10")
    drawdown_values = parse_float_csv("STABILITY_SWEEP_DRAWDOWN_VALUES", "2,5,12")
    tp_values = parse_float_csv("STABILITY_SWEEP_TAKE_PROFIT_VALUES", "0.010,0.012,0.015,0.020")
    sl_values = parse_float_csv("STABILITY_SWEEP_STOP_LOSS_VALUES", "0.010,0.015,0.020")

    min_qualified_events = int(os.getenv("STABILITY_SWEEP_MIN_QUALIFIED_EVENTS", "10"))

    print(f"Filas journal: {len(df)}")
    print(f"Señales únicas: {df['signal_key'].nunique()}")
    print(f"Min eventos para calificar: {min_qualified_events}")

    rows = []
    best_replay = pd.DataFrame()
    best_score_tuple = None

    filter_cache = {}

    combos = list(
        itertools.product(
            decision_sets,
            ask_ranges,
            spread_max_values,
            score_ranges,
            min_obs_values,
            lookback_values,
            max_gap_values,
            drawdown_values,
        )
    )

    total_replay_combos = len(combos) * len(tp_values) * len(sl_values)
    print(f"Combinaciones filtro: {len(combos)}")
    print(f"Combinaciones con TP/SL: {total_replay_combos}")

    for (
        decisions,
        ask_range,
        spread_max,
        score_range,
        min_obs,
        lookback,
        max_gap,
        drawdown,
    ) in combos:
        ask_min, ask_max = ask_range
        score_min, score_max = score_range

        filter_key = (
            decisions,
            ask_min,
            ask_max,
            spread_max,
            score_min,
            score_max,
            min_obs,
            lookback,
            max_gap,
            drawdown,
        )

        if filter_key not in filter_cache:
            set_env_config(
                decisions,
                ask_min,
                ask_max,
                spread_max,
                score_min,
                score_max,
                min_obs,
                lookback,
                max_gap,
                drawdown,
                0.02,
                0.02,
            )
            _, events = base_and_events(csr, df)
            filter_cache[filter_key] = events
        else:
            events = filter_cache[filter_key]

        if events.empty:
            continue

        for tp, sl in itertools.product(tp_values, sl_values):
            set_env_config(
                decisions,
                ask_min,
                ask_max,
                spread_max,
                score_min,
                score_max,
                min_obs,
                lookback,
                max_gap,
                drawdown,
                tp,
                sl,
            )

            replay = csr.replay_events(events, df)

            if replay.empty:
                continue

            row = summarize_result(
                replay,
                events,
                decisions,
                ask_min,
                ask_max,
                spread_max,
                score_min,
                score_max,
                min_obs,
                lookback,
                max_gap,
                drawdown,
                tp,
                sl,
            )

            rows.append(row)

            score_tuple = (
                row["replay_events"] >= min_qualified_events,
                row["avg_exit_pnl_pct"],
                row["median_exit_pnl_pct"],
                -row["hit_sl_rate"],
                row["win_rate_exit"],
                row["replay_events"],
            )

            if best_score_tuple is None or score_tuple > best_score_tuple:
                best_score_tuple = score_tuple
                best_replay = replay.copy()

    if not rows:
        print("No hubo resultados en el sweep.")
        return

    summary = pd.DataFrame(rows)
    summary["qualified"] = (
        (summary["replay_events"] >= min_qualified_events)
        & (summary["avg_exit_pnl_pct"] > 0)
        & (summary["median_exit_pnl_pct"] >= 0)
        & (summary["hit_sl_rate"] <= 10)
        & (summary["win_rate_exit"] >= 45)
    )

    summary = summary.sort_values(
        [
            "qualified",
            "avg_exit_pnl_pct",
            "median_exit_pnl_pct",
            "hit_sl_rate",
            "replay_events",
        ],
        ascending=[False, False, False, True, False],
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT, index=False)

    if not best_replay.empty:
        best_replay.to_csv(TOP_REPLAY_OUT, index=False)

    print(f"\nResultados sweep: {len(summary)}")
    print(f"Archivo: {OUT}")
    print(f"Replay mejor config: {TOP_REPLAY_OUT}")

    print("\n=== TOP 20 CONFIGS ===")
    cols = [
        "qualified",
        "replay_events",
        "unique_stable_signals",
        "avg_exit_pnl_pct",
        "median_exit_pnl_pct",
        "win_rate_exit",
        "hit_tp_rate",
        "hit_sl_rate",
        "worst_min_pnl_pct",
        "decisions",
        "ask_min",
        "ask_max",
        "score_min",
        "score_max",
        "min_observations",
        "max_bid_drawdown_pct",
        "take_profit",
        "stop_loss",
    ]
    print(summary[cols].head(20).to_string(index=False))

    qualified = summary[summary["qualified"]]

    print("\n=== CONFIGS CALIFICADAS ===")
    if qualified.empty:
        print("Ninguna configuración alcanzó el mínimo de calidad.")
    else:
        print(qualified[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
