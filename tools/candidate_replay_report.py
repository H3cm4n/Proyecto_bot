from __future__ import annotations

from pathlib import Path
import os

import pandas as pd


JOURNAL = Path("data/candidate_journal.csv")


def safe_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def reason_tags(value: str) -> list[str]:
    if not isinstance(value, str):
        return []

    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


def summarize(df: pd.DataFrame, group_col: str, min_count: int = 5) -> pd.DataFrame:
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

    out = pd.DataFrame(rows)
    return out.sort_values(
        ["avg_exit_pnl_pct", "hit_tp_rate", "count"],
        ascending=[False, False, False],
    )


def simulate_forward(df: pd.DataFrame, horizon_minutes: int, take_profit: float, stop_loss: float) -> pd.DataFrame:
    rows = []

    for key, group in df.groupby("signal_key"):
        group = group.sort_values("observed_at_dt").reset_index(drop=True)

        for i, row in group.iterrows():
            entry_ask = row.get("best_ask")

            if pd.isna(entry_ask) or entry_ask <= 0 or entry_ask >= 0.99:
                continue

            start = row["observed_at_dt"]
            end = start + pd.Timedelta(minutes=horizon_minutes)

            future = group[
                (group["observed_at_dt"] > start)
                & (group["observed_at_dt"] <= end)
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
                bid = frow["best_bid"]

                if pd.isna(bid):
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

            result = row.to_dict()
            result.update(
                {
                    "entry_ask": entry_ask,
                    "future_points": len(future),
                    "horizon_minutes": horizon_minutes,
                    "take_profit_price": take_profit_price,
                    "stop_loss_price": stop_loss_price,
                    "max_future_bid": max_bid,
                    "min_future_bid": min_bid,
                    "last_future_bid": last_bid,
                    "first_exit_reason": first_exit_reason,
                    "first_exit_bid": first_exit_bid,
                    "first_exit_at": first_exit_at,
                    "max_pnl_pct": ((max_bid - entry_ask) / entry_ask) * 100,
                    "min_pnl_pct": ((min_bid - entry_ask) / entry_ask) * 100,
                    "final_pnl_pct": ((last_bid - entry_ask) / entry_ask) * 100,
                    "exit_pnl_pct": ((first_exit_bid - entry_ask) / entry_ask) * 100,
                    "hit_take_profit": first_exit_reason == "TAKE_PROFIT",
                    "hit_stop_loss": first_exit_reason == "STOP_LOSS",
                }
            )

            rows.append(result)

    return pd.DataFrame(rows)


def main() -> None:
    horizon_minutes = int(os.getenv("CANDIDATE_REPLAY_HORIZON_MINUTES", "180"))
    take_profit = float(os.getenv("PAPER_TAKE_PROFIT", "0.15"))
    stop_loss = float(os.getenv("PAPER_STOP_LOSS", "0.08"))
    min_count = int(os.getenv("CANDIDATE_REPLAY_MIN_COUNT", "3"))

    print("\n=== CANDIDATE REPLAY REPORT ===")
    print(f"Horizonte: {horizon_minutes} min")
    print(f"Take profit contrato: +{take_profit}")
    print(f"Stop loss contrato: -{stop_loss}")

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
            df[col] = safe_num(df[col])

    print(f"Candidatos registrados: {len(df)}")
    print(f"Señales únicas: {df['signal_key'].nunique()}")

    results = simulate_forward(
        df=df,
        horizon_minutes=horizon_minutes,
        take_profit=take_profit,
        stop_loss=stop_loss,
    )

    if results.empty:
        print("Todavía no hay suficientes observaciones futuras para replay.")
        print("Corre el monitor más tiempo y vuelve a ejecutar este reporte.")
        return

    print(f"\nHipótesis evaluadas con futuro: {len(results)}")

    print("\n=== RESUMEN GLOBAL ===")
    print(f"Win rate exit: {(results['exit_pnl_pct'] > 0).mean() * 100:.2f}%")
    print(f"Avg exit pnl %: {results['exit_pnl_pct'].mean():.2f}%")
    print(f"Median exit pnl %: {results['exit_pnl_pct'].median():.2f}%")
    print(f"Hit TP rate: {results['hit_take_profit'].mean() * 100:.2f}%")
    print(f"Hit SL rate: {results['hit_stop_loss'].mean() * 100:.2f}%")

    for col, title in [
        ("crypto_decision", "POR DECISIÓN"),
        ("crypto_alignment", "POR ALIGNMENT"),
        ("binance_bias", "POR BINANCE BIAS"),
        ("flow_support", "POR FLOW SUPPORT"),
        ("flow_bias", "POR FLOW BIAS"),
        ("crypto_symbol", "POR SÍMBOLO"),
    ]:
        summary = summarize(results, col, min_count=min_count)

        print(f"\n=== {title} ===")
        if summary.empty:
            print(f"No hay grupos con al menos {min_count} muestras.")
        else:
            print(summary.to_string(index=False))

    exploded = []

    for _, row in results.iterrows():
        for tag in reason_tags(row.get("crypto_decision_reasons", "")):
            item = row.to_dict()
            item["reason_tag"] = tag
            exploded.append(item)

    if exploded:
        reason_df = pd.DataFrame(exploded)
        reason_summary = summarize(reason_df, "reason_tag", min_count=min_count)

        print("\n=== POR REASON TAG ===")
        if reason_summary.empty:
            print(f"No hay reason tags con al menos {min_count} muestras.")
        else:
            print(reason_summary.to_string(index=False))

    cols = [
        "observed_at",
        "crypto_symbol",
        "outcome",
        "crypto_decision",
        "crypto_alignment",
        "binance_bias",
        "flow_support",
        "best_bid",
        "entry_ask",
        "spread",
        "score",
        "fair_edge_to_ask",
        "first_exit_reason",
        "exit_pnl_pct",
        "max_pnl_pct",
        "min_pnl_pct",
        "question",
    ]
    cols = [c for c in cols if c in results.columns]

    print("\n=== TOP HIPÓTESIS GANADORAS ===")
    print(results.sort_values("exit_pnl_pct", ascending=False)[cols].head(20).to_string(index=False))

    print("\n=== TOP HIPÓTESIS PERDEDORAS ===")
    print(results.sort_values("exit_pnl_pct", ascending=True)[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
