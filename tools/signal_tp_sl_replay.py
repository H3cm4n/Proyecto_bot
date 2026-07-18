from __future__ import annotations

from pathlib import Path
import os

import pandas as pd


JOURNAL = Path(os.getenv("CANDIDATE_JOURNAL_PATH", "data/candidate_journal.csv"))

DETAIL_OUT = Path(os.getenv("TPSL_DETAIL_OUT", "data/signal_tp_sl_replay.csv"))
SUMMARY_OUT = Path(os.getenv("TPSL_SUMMARY_OUT", "data/signal_tp_sl_summary.csv"))
SWEEP_OUT = Path(os.getenv("TPSL_SWEEP_OUT", "data/signal_tp_sl_policy_sweep.csv"))

LOOKBACK_HOURS = float(os.getenv("TPSL_LOOKBACK_HOURS", "6"))
ENTRY_COOLDOWN_MINUTES = int(os.getenv("TPSL_ENTRY_COOLDOWN_MINUTES", "10"))
CONFIRMATION_WINDOW_MINUTES = int(os.getenv("TPSL_CONFIRMATION_WINDOW_MINUTES", "10"))

ENTRY_DECISIONS = [
    x.strip()
    for x in os.getenv(
        "TPSL_ENTRY_DECISIONS",
        "CRYPTO_BUY_FAIR_EDGE,CRYPTO_WATCH_FAIR_EDGE",
    ).split(",")
    if x.strip()
]

TP_VALUES = [
    float(x.strip())
    for x in os.getenv("TPSL_TAKE_PROFITS", "1,2,3,4").split(",")
    if x.strip()
]

SL_VALUES = [
    float(x.strip())
    for x in os.getenv("TPSL_STOP_LOSSES", "2,4,6,8").split(",")
    if x.strip()
]

MAX_HOLDS = [
    int(x.strip())
    for x in os.getenv("TPSL_MAX_HOLDS", "30,60,120,180").split(",")
    if x.strip()
]

EDGE_VALUES = [
    float(x.strip())
    for x in os.getenv("TPSL_EDGE_VALUES", "0.10,0.15,0.20,0.25,0.30,0.35").split(",")
    if x.strip()
]

SCORE_VALUES = [
    float(x.strip())
    for x in os.getenv("TPSL_SCORE_VALUES", "70,75,80,85,90").split(",")
    if x.strip()
]

SPREAD_VALUES = [
    float(x.strip())
    for x in os.getenv("TPSL_SPREAD_VALUES", "0.01,0.02").split(",")
    if x.strip()
]

CONFIRM_VALUES = [
    int(x.strip())
    for x in os.getenv("TPSL_CONFIRM_VALUES", "1,2,3").split(",")
    if x.strip()
]

ASK_MIN_VALUES = [
    float(x.strip())
    for x in os.getenv("TPSL_ASK_MIN_VALUES", "0.45,0.50").split(",")
    if x.strip()
]

ASK_MAX_VALUES = [
    float(x.strip())
    for x in os.getenv("TPSL_ASK_MAX_VALUES", "0.56,0.60").split(",")
    if x.strip()
]

FLOW_POLICIES = [
    x.strip().upper()
    for x in os.getenv(
        "TPSL_FLOW_POLICIES",
        "ANY,BULLISH_ONLY,NO_BEARISH,BEARISH_ONLY,ALIGNED_BULLISH_ONLY,ALIGNED_BEARISH_ONLY",
    ).split(",")
    if x.strip()
]

MIN_OBSERVATIONS = int(os.getenv("TPSL_MIN_OBSERVATIONS", "3"))
MIN_UNIQUE_SIGNALS = int(os.getenv("TPSL_MIN_UNIQUE_SIGNALS", "1"))


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


def flow_state(alignment, flow) -> str:
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

    if policy == "ALIGNED_BULLISH_ONLY":
        return df[state.eq("ALIGNED_FLOW_BULLISH")]

    if policy == "ALIGNED_BEARISH_ONLY":
        return df[state.eq("ALIGNED_FLOW_BEARISH")]

    return df


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

    df["crypto_decision"] = df.get("crypto_decision", "").fillna("").astype(str)
    df["crypto_symbol"] = df.get("crypto_symbol", "").fillna("").astype(str)
    df["outcome"] = df.get("outcome", "").fillna("").astype(str)
    df["question"] = df.get("question", "").fillna("").astype(str)
    df["crypto_alignment"] = df.get("crypto_alignment", "").fillna("").astype(str).str.upper()
    df["flow_bias"] = df.get("flow_bias", "").fillna("").astype(str).str.upper()
    df["signal_key"] = df.apply(signal_key, axis=1)
    df["flow_state"] = df.apply(
        lambda row: flow_state(row.get("crypto_alignment"), row.get("flow_bias")),
        axis=1,
    )

    return df.sort_values("observed_at").reset_index(drop=True)


def confirmation_count(entry: pd.Series, history: pd.DataFrame) -> int:
    start = entry["observed_at"] - pd.Timedelta(minutes=CONFIRMATION_WINDOW_MINUTES)

    rows = history[
        history["signal_key"].eq(entry["signal_key"])
        & (history["observed_at"] >= start)
        & (history["observed_at"] <= entry["observed_at"])
        & history["crypto_decision"].isin(ENTRY_DECISIONS)
    ]

    return len(rows)


def select_entries(entries: pd.DataFrame) -> pd.DataFrame:
    if entries.empty:
        return entries.copy()

    entries = entries.sort_values("observed_at").copy()

    if ENTRY_COOLDOWN_MINUTES <= 0:
        entries["entry_selected"] = True
        entries["selection_reason"] = "NO_COOLDOWN"
        return entries

    selected_indices = []
    last_selected_by_key = {}

    cooldown = pd.Timedelta(minutes=ENTRY_COOLDOWN_MINUTES)

    for idx, row in entries.iterrows():
        key = row["signal_key"]
        current_time = row["observed_at"]
        last_time = last_selected_by_key.get(key)

        if last_time is None or current_time - last_time >= cooldown:
            selected_indices.append(idx)
            last_selected_by_key[key] = current_time

    selected = entries.loc[selected_indices].copy()
    selected["entry_selected"] = True
    selected["selection_reason"] = f"COOLDOWN_{ENTRY_COOLDOWN_MINUTES}_MIN"

    return selected


def simulate_trade(entry: pd.Series, history: pd.DataFrame, take_profit_pct: float, stop_loss_pct: float, max_hold_minutes: int) -> dict:
    entry_time = entry["observed_at"]
    entry_ask = safe_float(entry.get("best_ask"))
    entry_bid = safe_float(entry.get("best_bid"))

    base = {
        "entry_time": entry_time,
        "signal_key": entry.get("signal_key"),
        "crypto_symbol": entry.get("crypto_symbol"),
        "outcome": entry.get("outcome"),
        "question": entry.get("question"),
        "crypto_decision": entry.get("crypto_decision"),
        "crypto_alignment": entry.get("crypto_alignment"),
        "flow_bias": entry.get("flow_bias"),
        "flow_state": entry.get("flow_state"),
        "entry_bid": entry_bid,
        "entry_ask": entry_ask,
        "spread": safe_float(entry.get("spread")),
        "score": safe_float(entry.get("score")),
        "fair_edge_to_ask": safe_float(entry.get("fair_edge_to_ask")),
        "distance_pct": safe_float(entry.get("distance_pct")),
        "confirmation_count_10m": safe_float(entry.get("confirmation_count_10m"), 0),
        "take_profit_pct": take_profit_pct,
        "stop_loss_pct": stop_loss_pct,
        "max_hold_minutes": max_hold_minutes,
        "exit_time": None,
        "exit_bid": None,
        "exit_reason": "UNKNOWN",
        "pnl_pct": None,
        "minutes_open": None,
        "max_bid": None,
        "min_bid": None,
        "mfe_pct": None,
        "mae_pct": None,
        "future_rows": 0,
        "status": "UNKNOWN",
    }

    if entry_ask is None or entry_ask <= 0:
        base["status"] = "INVALID_ENTRY_ASK"
        return base

    end_time = entry_time + pd.Timedelta(minutes=max_hold_minutes)

    future = history[
        history["signal_key"].eq(entry["signal_key"])
        & (history["observed_at"] > entry_time)
        & (history["observed_at"] <= end_time)
        & history["best_bid"].notna()
    ].copy()

    base["future_rows"] = len(future)

    if future.empty:
        base["status"] = "NO_FUTURE_ROWS"
        return base

    max_bid = future["best_bid"].max()
    min_bid = future["best_bid"].min()

    base["max_bid"] = max_bid
    base["min_bid"] = min_bid
    base["mfe_pct"] = ((max_bid - entry_ask) / entry_ask) * 100
    base["mae_pct"] = ((min_bid - entry_ask) / entry_ask) * 100

    exit_row = None
    exit_reason = None

    for _, row in future.iterrows():
        bid = safe_float(row.get("best_bid"))

        if bid is None:
            continue

        pnl_pct = ((bid - entry_ask) / entry_ask) * 100

        if pnl_pct >= take_profit_pct:
            exit_row = row
            exit_reason = "TAKE_PROFIT"
            break

        if pnl_pct <= -stop_loss_pct:
            exit_row = row
            exit_reason = "STOP_LOSS"
            break

    if exit_row is None:
        exit_row = future.iloc[-1]
        exit_reason = "HORIZON_EXIT"

    exit_bid = safe_float(exit_row.get("best_bid"))
    exit_time = exit_row["observed_at"]
    pnl_pct = ((exit_bid - entry_ask) / entry_ask) * 100 if exit_bid is not None else None
    minutes_open = (exit_time - entry_time).total_seconds() / 60

    base.update(
        {
            "exit_time": exit_time,
            "exit_bid": exit_bid,
            "exit_reason": exit_reason,
            "pnl_pct": pnl_pct,
            "minutes_open": minutes_open,
            "status": "EVALUATED",
        }
    )

    return base


def build_summary(detail: pd.DataFrame) -> pd.DataFrame:
    evaluated = detail[detail["status"].eq("EVALUATED")].copy()

    if evaluated.empty:
        return pd.DataFrame()

    rows = []

    group_cols = [
        "max_hold_minutes",
        "take_profit_pct",
        "stop_loss_pct",
        "flow_state",
    ]

    for key, g in evaluated.groupby(group_cols, dropna=False):
        item = dict(zip(group_cols, key))

        item.update(
            {
                "observations": len(g),
                "unique_signals": g["signal_key"].nunique(),
                "avg_pnl_pct": g["pnl_pct"].mean(),
                "median_pnl_pct": g["pnl_pct"].median(),
                "win_rate_pct": (g["pnl_pct"] > 0).mean() * 100,
                "take_profit_rate_pct": (g["exit_reason"] == "TAKE_PROFIT").mean() * 100,
                "stop_loss_rate_pct": (g["exit_reason"] == "STOP_LOSS").mean() * 100,
                "horizon_exit_rate_pct": (g["exit_reason"] == "HORIZON_EXIT").mean() * 100,
                "avg_mfe_pct": g["mfe_pct"].mean(),
                "avg_mae_pct": g["mae_pct"].mean(),
                "worst_pnl_pct": g["pnl_pct"].min(),
                "best_pnl_pct": g["pnl_pct"].max(),
                "avg_minutes_open": g["minutes_open"].mean(),
                "avg_edge": g["fair_edge_to_ask"].mean(),
                "avg_score": g["score"].mean(),
                "avg_spread": g["spread"].mean(),
                "avg_entry_ask": g["entry_ask"].mean(),
            }
        )

        rows.append(item)

    return pd.DataFrame(rows).sort_values(
        ["avg_pnl_pct", "median_pnl_pct", "win_rate_pct"],
        ascending=[False, False, False],
    )


def build_policy_sweep(detail: pd.DataFrame) -> pd.DataFrame:
    evaluated = detail[detail["status"].eq("EVALUATED")].copy()

    if evaluated.empty:
        return pd.DataFrame()

    rows = []

    for max_hold in sorted(evaluated["max_hold_minutes"].dropna().unique()):
        hdf = evaluated[evaluated["max_hold_minutes"].eq(max_hold)].copy()

        for tp in sorted(hdf["take_profit_pct"].dropna().unique()):
            for sl in sorted(hdf["stop_loss_pct"].dropna().unique()):
                base_tp_sl = hdf[
                    hdf["take_profit_pct"].eq(tp)
                    & hdf["stop_loss_pct"].eq(sl)
                ].copy()

                for min_edge in EDGE_VALUES:
                    for min_score in SCORE_VALUES:
                        for max_spread in SPREAD_VALUES:
                            for min_confirm in CONFIRM_VALUES:
                                for ask_min in ASK_MIN_VALUES:
                                    for ask_max in ASK_MAX_VALUES:
                                        if ask_min > ask_max:
                                            continue

                                        base = base_tp_sl[
                                            (base_tp_sl["fair_edge_to_ask"] >= min_edge)
                                            & (base_tp_sl["score"] >= min_score)
                                            & (base_tp_sl["spread"] <= max_spread)
                                            & (base_tp_sl["confirmation_count_10m"] >= min_confirm)
                                            & (base_tp_sl["entry_ask"] >= ask_min)
                                            & (base_tp_sl["entry_ask"] <= ask_max)
                                        ].copy()

                                        if base.empty:
                                            continue

                                        for policy in FLOW_POLICIES:
                                            g = apply_flow_policy(base, policy)

                                            if g.empty:
                                                continue

                                            observations = len(g)
                                            unique_signals = g["signal_key"].nunique()

                                            qualified_sample = (
                                                observations >= MIN_OBSERVATIONS
                                                and unique_signals >= MIN_UNIQUE_SIGNALS
                                            )

                                            avg_pnl = g["pnl_pct"].mean()
                                            median_pnl = g["pnl_pct"].median()
                                            win_rate = (g["pnl_pct"] > 0).mean() * 100

                                            candidate_policy = (
                                                qualified_sample
                                                and avg_pnl > 0
                                                and median_pnl >= 0
                                                and win_rate >= 40
                                            )

                                            rows.append(
                                                {
                                                    "candidate_policy": candidate_policy,
                                                    "qualified_sample": qualified_sample,
                                                    "max_hold_minutes": max_hold,
                                                    "take_profit_pct": tp,
                                                    "stop_loss_pct": sl,
                                                    "flow_policy": policy,
                                                    "observations": observations,
                                                    "unique_signals": unique_signals,
                                                    "avg_pnl_pct": avg_pnl,
                                                    "median_pnl_pct": median_pnl,
                                                    "win_rate_pct": win_rate,
                                                    "take_profit_rate_pct": (g["exit_reason"] == "TAKE_PROFIT").mean() * 100,
                                                    "stop_loss_rate_pct": (g["exit_reason"] == "STOP_LOSS").mean() * 100,
                                                    "horizon_exit_rate_pct": (g["exit_reason"] == "HORIZON_EXIT").mean() * 100,
                                                    "avg_mfe_pct": g["mfe_pct"].mean(),
                                                    "avg_mae_pct": g["mae_pct"].mean(),
                                                    "worst_pnl_pct": g["pnl_pct"].min(),
                                                    "best_pnl_pct": g["pnl_pct"].max(),
                                                    "avg_minutes_open": g["minutes_open"].mean(),
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

    if result.empty:
        return result

    return result.sort_values(
        [
            "candidate_policy",
            "qualified_sample",
            "avg_pnl_pct",
            "median_pnl_pct",
            "win_rate_pct",
            "observations",
        ],
        ascending=[False, False, False, False, False, False],
    )


def main() -> None:
    print("\n=== SIGNAL TP/SL REPLAY ===")

    df = load_journal()

    if df.empty:
        print("candidate_journal.csv está vacío.")
        return

    end = df["observed_at"].max()
    start = end - pd.Timedelta(hours=LOOKBACK_HOURS)

    recent = df[(df["observed_at"] >= start) & (df["observed_at"] <= end)].copy()

    raw_entries = recent[
        recent["crypto_decision"].isin(ENTRY_DECISIONS)
        & recent["best_ask"].notna()
        & (recent["best_ask"] > 0)
    ].copy()

    if raw_entries.empty:
        print("No hay entradas BUY/WATCH recientes para simular.")
        return

    raw_entries["confirmation_count_10m"] = raw_entries.apply(
        lambda row: confirmation_count(row, df),
        axis=1,
    )

    entries = select_entries(raw_entries)

    print(f"Ventana: {start} -> {end}")
    print(f"Filas recientes: {len(recent)}")
    print(f"Entradas raw: {len(raw_entries)}")
    print(f"Entradas seleccionadas: {len(entries)}")
    print(f"Cooldown por señal: {ENTRY_COOLDOWN_MINUTES} min")
    print(f"TPs: {TP_VALUES}")
    print(f"SLs: {SL_VALUES}")
    print(f"Max holds: {MAX_HOLDS}")

    rows = []

    for _, entry in entries.iterrows():
        for max_hold in MAX_HOLDS:
            for tp in TP_VALUES:
                for sl in SL_VALUES:
                    rows.append(simulate_trade(entry, df, tp, sl, max_hold))

    detail = pd.DataFrame(rows)
    summary = build_summary(detail)
    sweep = build_policy_sweep(detail)

    DETAIL_OUT.parent.mkdir(parents=True, exist_ok=True)
    detail.to_csv(DETAIL_OUT, index=False)
    summary.to_csv(SUMMARY_OUT, index=False)
    sweep.to_csv(SWEEP_OUT, index=False)

    print(f"Archivo detalle: {DETAIL_OUT}")
    print(f"Archivo resumen: {SUMMARY_OUT}")
    print(f"Archivo sweep: {SWEEP_OUT}")

    print("\n=== ENTRADAS SELECCIONADAS ===")
    entry_cols = [
        "observed_at",
        "crypto_symbol",
        "outcome",
        "crypto_decision",
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_edge_to_ask",
        "confirmation_count_10m",
        "crypto_alignment",
        "flow_bias",
        "flow_state",
        "question",
    ]
    entry_cols = [c for c in entry_cols if c in entries.columns]
    print(entries[entry_cols].to_string(index=False))

    print("\n=== RESUMEN TP/SL POR FLOW ===")
    if summary.empty:
        print("No hubo simulaciones evaluables.")
    else:
        cols = [
            "max_hold_minutes",
            "take_profit_pct",
            "stop_loss_pct",
            "flow_state",
            "observations",
            "unique_signals",
            "avg_pnl_pct",
            "median_pnl_pct",
            "win_rate_pct",
            "take_profit_rate_pct",
            "stop_loss_rate_pct",
            "horizon_exit_rate_pct",
            "avg_mfe_pct",
            "avg_mae_pct",
            "worst_pnl_pct",
            "best_pnl_pct",
            "avg_minutes_open",
            "avg_edge",
            "avg_score",
            "avg_spread",
        ]
        print(summary[cols].head(40).to_string(index=False))

    print("\n=== TOP POLICY SWEEP ===")
    if sweep.empty:
        print("No hubo políticas evaluables.")
    else:
        cols = [
            "candidate_policy",
            "qualified_sample",
            "max_hold_minutes",
            "take_profit_pct",
            "stop_loss_pct",
            "flow_policy",
            "observations",
            "unique_signals",
            "avg_pnl_pct",
            "median_pnl_pct",
            "win_rate_pct",
            "take_profit_rate_pct",
            "stop_loss_rate_pct",
            "horizon_exit_rate_pct",
            "avg_mfe_pct",
            "avg_mae_pct",
            "worst_pnl_pct",
            "best_pnl_pct",
            "avg_minutes_open",
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
        print(sweep[cols].head(50).to_string(index=False))

        candidates = sweep[sweep["candidate_policy"] == True]

        print("\n=== CANDIDATE POLICIES ONLY ===")
        if candidates.empty:
            print("No hubo políticas candidatas positivas con los mínimos actuales.")
        else:
            print(candidates[cols].head(50).to_string(index=False))


if __name__ == "__main__":
    main()
