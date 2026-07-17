from __future__ import annotations

from pathlib import Path
import os
import sys

import pandas as pd


JOURNAL = Path(os.getenv("CANDIDATE_JOURNAL_PATH", "data/candidate_journal.csv"))
STABLE_OUT = Path(os.getenv("STABLE_CANDIDATES_PATH", "data/stable_candidate_events.csv"))
REPLAY_OUT = Path(os.getenv("STABLE_REPLAY_PATH", "data/stable_candidate_replay.csv"))


def env_float(name: str, default: float) -> float:
    raw = os.getenv(name)

    if raw is None or raw == "":
        return default

    try:
        return float(raw)
    except ValueError:
        return default


def env_optional_float(name: str) -> float | None:
    raw = os.getenv(name)

    if raw is None or raw == "":
        return None

    try:
        return float(raw)
    except ValueError:
        return None


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)

    if raw is None or raw == "":
        return default

    try:
        return int(raw)
    except ValueError:
        return default


def env_csv(name: str, default: str) -> set[str]:
    raw = os.getenv(name, default)

    return {
        item.strip()
        for item in raw.split(",")
        if item.strip()
    }


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


def split_reasons(value) -> set[str]:
    return {
        item.strip()
        for item in safe_str(value).split(",")
        if item.strip()
    }


def bucket(value: float | None, cuts: list[float], labels: list[str]) -> str:
    if value is None or pd.isna(value):
        return "UNKNOWN"

    for cut, label in zip(cuts, labels):
        if value <= cut:
            return label

    return labels[-1]


def candidate_key(row) -> str:
    key = safe_str(row.get("signal_key")).strip()

    if key:
        return key

    token_id = safe_str(row.get("token_id")).strip()

    if token_id:
        return token_id

    return "|".join(
        [
            safe_str(row.get("crypto_symbol")).strip(),
            safe_str(row.get("outcome")).strip(),
            safe_str(row.get("question")).strip(),
        ]
    )


def classify_base_candidate(row) -> tuple[bool, list[str]]:
    symbols = env_csv("STABILITY_SYMBOLS", "BTCUSDT")
    allowed_decisions = env_csv(
        "STABILITY_ALLOWED_DECISIONS",
        "CRYPTO_WAIT_BINANCE_NOT_ALIGNED",
    )
    hard_reject_reasons = env_csv(
        "STABILITY_HARD_REJECT_REASONS",
        ",".join(
            [
                "INCOMPLETE_ORDERBOOK",
                "BINANCE_CONFLICT",
                "CONFLICT",
                "REL_SPREAD_TOO_HIGH",
                "LOW_TOP_LIQUIDITY",
            ]
        ),
    )

    ask_min = env_float("STABILITY_ASK_MIN", 0.065)
    ask_max = env_float("STABILITY_ASK_MAX", 0.080)
    spread_max = env_float("STABILITY_SPREAD_MAX", 0.001)
    score_min = env_float("STABILITY_SCORE_MIN", 65.0)
    score_max = env_optional_float("STABILITY_SCORE_MAX")

    require_trade_direction = os.getenv("STABILITY_TRADE_DIRECTION", "BULLISH").upper()
    require_flow_support = os.getenv("STABILITY_REQUIRE_FLOW_SUPPORT", "0") == "1"

    failures: list[str] = []

    symbol = safe_str(row.get("crypto_symbol")).strip().upper()
    decision = safe_str(row.get("crypto_decision")).strip()
    alignment = safe_str(row.get("crypto_alignment")).strip().upper()
    trade_direction = safe_str(row.get("trade_direction")).strip().upper()
    flow_support = safe_str(row.get("flow_support")).strip().upper()
    reasons = split_reasons(row.get("crypto_decision_reasons"))

    best_bid = safe_float(row.get("best_bid"))
    best_ask = safe_float(row.get("best_ask"))
    spread = safe_float(row.get("spread"))
    score = safe_float(row.get("score"))

    if symbol not in symbols:
        failures.append("SYMBOL_NOT_ALLOWED")

    if decision not in allowed_decisions:
        failures.append("DECISION_NOT_ALLOWED")

    if require_trade_direction and trade_direction != require_trade_direction:
        failures.append("TRADE_DIRECTION_NOT_ALLOWED")

    if alignment == "CONFLICT":
        failures.append("ALIGNMENT_CONFLICT")

    if hard_reject_reasons.intersection(reasons):
        failures.append("HARD_REJECT_REASON")

    if require_flow_support and flow_support != "SUPPORTS":
        failures.append("FLOW_NOT_SUPPORTING")

    if best_bid is None or best_ask is None:
        failures.append("MISSING_BID_ASK")
    else:
        if best_bid <= 0 or best_ask <= 0:
            failures.append("BAD_BID_ASK")

        if best_ask < ask_min:
            failures.append("ASK_TOO_LOW_FOR_STABILITY")

        if best_ask > ask_max:
            failures.append("ASK_TOO_HIGH_FOR_STABILITY")

    if spread is None and best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid

    if spread is None:
        failures.append("MISSING_SPREAD")
    elif spread > spread_max:
        failures.append("SPREAD_TOO_WIDE_FOR_STABILITY")

    if score is None:
        failures.append("MISSING_SCORE")
    else:
        if score < score_min:
            failures.append("SCORE_TOO_LOW_FOR_STABILITY")

        if score_max is not None and score > score_max:
            failures.append("SCORE_TOO_HIGH_FOR_STABILITY")

    return len(failures) == 0, failures


def build_stable_events(df: pd.DataFrame) -> pd.DataFrame:
    min_obs = env_int("STABILITY_MIN_OBSERVATIONS", 3)
    lookback_minutes = env_int("STABILITY_LOOKBACK_MINUTES", 15)
    max_gap_minutes = env_float("STABILITY_MAX_GAP_MINUTES", 7.0)
    max_bid_drawdown_pct = env_float("STABILITY_MAX_BID_DRAWDOWN_PCT", 12.0)
    max_ask_drawdown_pct = env_float("STABILITY_MAX_ASK_DRAWDOWN_PCT", 12.0)
    entry_cooldown_minutes = env_int("STABILITY_ENTRY_COOLDOWN_MINUTES", 30)

    events = []
    last_event_by_key: dict[str, pd.Timestamp] = {}

    for key, group in df.groupby("signal_key", dropna=False):
        group = group.sort_values("observed_at_dt").reset_index(drop=True)

        for idx, row in group.iterrows():
            if not bool(row["_base_pass"]):
                continue

            now = row["observed_at_dt"]
            last_event = last_event_by_key.get(key)

            if last_event is not None:
                age_minutes = (now - last_event).total_seconds() / 60

                if age_minutes < entry_cooldown_minutes:
                    continue

            window_start = now - pd.Timedelta(minutes=lookback_minutes)
            window = group[
                (group["observed_at_dt"] >= window_start)
                & (group["observed_at_dt"] <= now)
                & (group["_base_pass"])
            ].copy()

            if len(window) < min_obs:
                continue

            tail = window.tail(min_obs).copy()

            gaps = tail["observed_at_dt"].diff().dropna().dt.total_seconds() / 60

            if not gaps.empty and gaps.max() > max_gap_minutes:
                continue

            bids = pd.to_numeric(tail["best_bid"], errors="coerce").dropna()
            asks = pd.to_numeric(tail["best_ask"], errors="coerce").dropna()
            scores = pd.to_numeric(tail["score"], errors="coerce").dropna()
            spreads = pd.to_numeric(tail["spread"], errors="coerce").dropna()

            if bids.empty or asks.empty:
                continue

            current_bid = safe_float(row.get("best_bid"))
            current_ask = safe_float(row.get("best_ask"))

            if current_bid is None or current_ask is None:
                continue

            bid_peak = float(bids.max())
            ask_peak = float(asks.max())

            bid_drawdown_pct = ((bid_peak - current_bid) / bid_peak) * 100 if bid_peak else 0.0
            ask_drawdown_pct = ((ask_peak - current_ask) / ask_peak) * 100 if ask_peak else 0.0

            if bid_drawdown_pct > max_bid_drawdown_pct:
                continue

            if ask_drawdown_pct > max_ask_drawdown_pct:
                continue

            first = tail.iloc[0]
            minutes_stable = (now - first["observed_at_dt"]).total_seconds() / 60

            event = row.to_dict()
            event.update(
                {
                    "stable_signal_key": key,
                    "stable_observations": len(tail),
                    "stable_minutes": minutes_stable,
                    "stable_first_observed_at": first["observed_at"],
                    "stable_last_observed_at": row["observed_at"],
                    "stable_bid_start": safe_float(first.get("best_bid")),
                    "stable_bid_current": current_bid,
                    "stable_bid_peak": bid_peak,
                    "stable_bid_min": float(bids.min()),
                    "stable_bid_drawdown_pct": bid_drawdown_pct,
                    "stable_ask_start": safe_float(first.get("best_ask")),
                    "stable_ask_current": current_ask,
                    "stable_ask_peak": ask_peak,
                    "stable_ask_min": float(asks.min()),
                    "stable_ask_drawdown_pct": ask_drawdown_pct,
                    "stable_score_min": float(scores.min()) if not scores.empty else None,
                    "stable_score_max": float(scores.max()) if not scores.empty else None,
                    "stable_spread_max": float(spreads.max()) if not spreads.empty else None,
                }
            )

            events.append(event)
            last_event_by_key[key] = now

    return pd.DataFrame(events)


def replay_events(events: pd.DataFrame, all_rows: pd.DataFrame) -> pd.DataFrame:
    horizon_minutes = env_int("STABILITY_REPLAY_HORIZON_MINUTES", 60)
    take_profit = env_float("STABILITY_TAKE_PROFIT", 0.02)
    stop_loss = env_float("STABILITY_STOP_LOSS", 0.02)

    if events.empty:
        return pd.DataFrame()

    grouped = {
        key: group.sort_values("observed_at_dt").reset_index(drop=True)
        for key, group in all_rows.groupby("signal_key", dropna=False)
    }

    rows = []

    for _, entry in events.iterrows():
        key = entry["signal_key"]
        group = grouped.get(key)

        if group is None or group.empty:
            continue

        entry_time = entry["observed_at_dt"]
        entry_ask = safe_float(entry.get("best_ask"))

        if entry_ask is None or entry_ask <= 0 or entry_ask >= 0.99:
            continue

        end_time = entry_time + pd.Timedelta(minutes=horizon_minutes)

        future = group[
            (group["observed_at_dt"] > entry_time)
            & (group["observed_at_dt"] <= end_time)
        ].copy()

        future = future[future["best_bid"].notna()]

        if future.empty:
            continue

        take_profit_price = min(0.99, entry_ask + take_profit)
        stop_loss_price = max(0.01, entry_ask - stop_loss)

        max_bid = future["best_bid"].max()
        min_bid = future["best_bid"].min()
        last_bid = future.iloc[-1]["best_bid"]

        first_exit_reason = "HORIZON"
        first_exit_bid = last_bid
        first_exit_at = future.iloc[-1]["observed_at"]

        for _, frow in future.iterrows():
            bid = safe_float(frow.get("best_bid"))

            if bid is None:
                continue

            if bid >= take_profit_price:
                first_exit_reason = "TAKE_PROFIT"
                first_exit_bid = bid
                first_exit_at = frow["observed_at"]
                break

            if bid <= stop_loss_price:
                first_exit_reason = "STOP_LOSS"
                first_exit_bid = bid
                first_exit_at = frow["observed_at"]
                break

        result = entry.to_dict()
        result.update(
            {
                "future_points": len(future),
                "replay_horizon_minutes": horizon_minutes,
                "entry_ask": entry_ask,
                "take_profit_price": take_profit_price,
                "stop_loss_price": stop_loss_price,
                "max_future_bid": max_bid,
                "min_future_bid": min_bid,
                "last_future_bid": last_bid,
                "first_exit_reason": first_exit_reason,
                "first_exit_bid": first_exit_bid,
                "first_exit_at": first_exit_at,
                "exit_pnl_pct": ((first_exit_bid - entry_ask) / entry_ask) * 100,
                "max_pnl_pct": ((max_bid - entry_ask) / entry_ask) * 100,
                "min_pnl_pct": ((min_bid - entry_ask) / entry_ask) * 100,
                "hit_take_profit": first_exit_reason == "TAKE_PROFIT",
                "hit_stop_loss": first_exit_reason == "STOP_LOSS",
            }
        )

        rows.append(result)

    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, group_col: str, min_count: int = 3) -> pd.DataFrame:
    if df.empty or group_col not in df.columns:
        return pd.DataFrame()

    rows = []

    for key, group in df.groupby(group_col, dropna=False):
        if len(group) < min_count:
            continue

        rows.append(
            {
                group_col: key,
                "count": len(group),
                "avg_exit_pnl_pct": group["exit_pnl_pct"].mean(),
                "median_exit_pnl_pct": group["exit_pnl_pct"].median(),
                "avg_max_pnl_pct": group["max_pnl_pct"].mean(),
                "hit_tp_rate": group["hit_take_profit"].mean() * 100,
                "hit_sl_rate": group["hit_stop_loss"].mean() * 100,
                "win_rate_exit": (group["exit_pnl_pct"] > 0).mean() * 100,
            }
        )

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values(
        ["avg_exit_pnl_pct", "hit_tp_rate", "count"],
        ascending=[False, False, False],
    )


def main() -> None:
    print("\n=== CANDIDATE STABILITY REPORT ===")

    if not JOURNAL.exists():
        print(f"No existe {JOURNAL}")
        return

    try:
        df = pd.read_csv(JOURNAL)
    except pd.errors.EmptyDataError:
        print("candidate_journal.csv está vacío.")
        return

    if df.empty:
        print("No hay candidatos.")
        return

    df = df.copy()

    if "signal_key" not in df.columns:
        df["signal_key"] = df.apply(candidate_key, axis=1)
    else:
        df["signal_key"] = df["signal_key"].fillna("").astype(str)
        missing_key = df["signal_key"].str.strip().eq("")
        df.loc[missing_key, "signal_key"] = df[missing_key].apply(candidate_key, axis=1)

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

    base_results = df.apply(classify_base_candidate, axis=1)
    df["_base_pass"] = base_results.apply(lambda item: item[0])
    df["_base_failures"] = base_results.apply(lambda item: ",".join(item[1]))

    print(f"Filas journal: {len(df)}")
    print(f"Señales únicas: {df['signal_key'].nunique()}")
    print(f"Candidatos base: {int(df['_base_pass'].sum())}")

    print("\n=== CONFIG ===")
    print(f"Decisiones permitidas: {os.getenv('STABILITY_ALLOWED_DECISIONS', 'CRYPTO_WAIT_BINANCE_NOT_ALIGNED')}")
    print(f"Ask min/max: {env_float('STABILITY_ASK_MIN', 0.065)} / {env_float('STABILITY_ASK_MAX', 0.080)}")
    print(f"Spread max: {env_float('STABILITY_SPREAD_MAX', 0.001)}")
    print(f"Score min/max: {env_float('STABILITY_SCORE_MIN', 65.0)} / {env_optional_float('STABILITY_SCORE_MAX')}")
    print(f"Observaciones requeridas: {env_int('STABILITY_MIN_OBSERVATIONS', 3)}")
    print(f"Lookback min: {env_int('STABILITY_LOOKBACK_MINUTES', 15)}")
    print(f"Max gap min: {env_float('STABILITY_MAX_GAP_MINUTES', 7.0)}")
    print(f"Max bid drawdown %: {env_float('STABILITY_MAX_BID_DRAWDOWN_PCT', 12.0)}")

    if int(df["_base_pass"].sum()) == 0:
        print("\nNo hubo candidatos base. Top fallas:")
        fail_series = df["_base_failures"].str.split(",").explode()
        fail_series = fail_series[fail_series.notna() & (fail_series != "")]
        print(fail_series.value_counts().head(20).to_string())
        return

    events = build_stable_events(df)

    if events.empty:
        print("\nNo hubo candidatos estables.")
        print("\nTop fallas base:")
        fail_series = df["_base_failures"].str.split(",").explode()
        fail_series = fail_series[fail_series.notna() & (fail_series != "")]
        print(fail_series.value_counts().head(20).to_string())
        return

    STABLE_OUT.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(STABLE_OUT, index=False)

    print(f"\nEventos estables: {len(events)}")
    print(f"Señales únicas estables: {events['signal_key'].nunique()}")
    print(f"Archivo eventos: {STABLE_OUT}")

    replay = replay_events(events, df)

    if replay.empty:
        print("\nNo hay suficientes puntos futuros para replay de estabilidad.")
        return

    replay["ask_bucket"] = replay["entry_ask"].apply(
        lambda x: bucket(x, [0.06, 0.07, 0.08, 0.10], ["<=0.06", "<=0.07", "<=0.08", "<=0.10", ">0.10"])
    )
    replay["score_bucket"] = replay["score"].apply(
        lambda x: bucket(x, [65, 70, 80], ["<=65", "<=70", "<=80", ">80"])
    )
    replay["stable_drawdown_bucket"] = replay["stable_bid_drawdown_pct"].apply(
        lambda x: bucket(x, [2, 5, 10, 15], ["<=2%", "<=5%", "<=10%", "<=15%", ">15%"])
    )

    REPLAY_OUT.parent.mkdir(parents=True, exist_ok=True)
    replay.to_csv(REPLAY_OUT, index=False)

    print(f"\nReplay eventos estables: {len(replay)}")
    print(f"Archivo replay: {REPLAY_OUT}")

    print("\n=== RESUMEN ESTABILIDAD ===")
    print(f"Win rate exit: {(replay['exit_pnl_pct'] > 0).mean() * 100:.2f}%")
    print(f"Avg exit pnl %: {replay['exit_pnl_pct'].mean():.2f}%")
    print(f"Median exit pnl %: {replay['exit_pnl_pct'].median():.2f}%")
    print(f"Hit TP rate: {replay['hit_take_profit'].mean() * 100:.2f}%")
    print(f"Hit SL rate: {replay['hit_stop_loss'].mean() * 100:.2f}%")

    for col, title in [
        ("crypto_decision", "POR DECISIÓN"),
        ("crypto_alignment", "POR ALIGNMENT"),
        ("binance_bias", "POR BINANCE BIAS"),
        ("flow_support", "POR FLOW SUPPORT"),
        ("ask_bucket", "POR ASK BUCKET"),
        ("score_bucket", "POR SCORE BUCKET"),
        ("stable_drawdown_bucket", "POR DRAWDOWN ESTABLE"),
    ]:
        print(f"\n=== {title} ===")
        summary = summarize(replay, col, min_count=3)

        if summary.empty:
            print("Sin grupos suficientes.")
        else:
            print(summary.to_string(index=False))

    cols = [
        "observed_at",
        "crypto_symbol",
        "outcome",
        "crypto_decision",
        "crypto_alignment",
        "binance_bias",
        "flow_support",
        "entry_ask",
        "best_bid",
        "spread",
        "score",
        "stable_observations",
        "stable_minutes",
        "stable_bid_drawdown_pct",
        "first_exit_reason",
        "exit_pnl_pct",
        "max_pnl_pct",
        "min_pnl_pct",
        "question",
    ]
    cols = [col for col in cols if col in replay.columns]

    print("\n=== TOP ESTABLES GANADORES ===")
    print(replay.sort_values("exit_pnl_pct", ascending=False)[cols].head(20).to_string(index=False))

    print("\n=== TOP ESTABLES PERDEDORES ===")
    print(replay.sort_values("exit_pnl_pct", ascending=True)[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
