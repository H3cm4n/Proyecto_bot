from __future__ import annotations

from pathlib import Path
import itertools
import os

import pandas as pd


TRADES = Path(os.getenv("PAPER_TRADES_PATH", "data/paper_trades.csv"))
JOURNAL = Path(os.getenv("CANDIDATE_JOURNAL_PATH", "data/candidate_journal.csv"))
OUT = Path(os.getenv("PAPER_COMBINED_EXIT_OUT", "data/paper_combined_exit_replay.csv"))
SUMMARY_OUT = Path(os.getenv("PAPER_COMBINED_EXIT_SUMMARY_OUT", "data/paper_combined_exit_summary.csv"))


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


def parse_int_csv(name: str, default: str) -> list[int]:
    raw = os.getenv(name, default)
    values = []

    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue

        try:
            values.append(int(item))
        except ValueError:
            pass

    return values


def parse_float_csv(name: str, default: str) -> list[float]:
    raw = os.getenv(name, default)
    values = []

    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue

        try:
            values.append(float(item))
        except ValueError:
            pass

    return values


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not TRADES.exists():
        raise FileNotFoundError(f"No existe {TRADES}")

    if not JOURNAL.exists():
        raise FileNotFoundError(f"No existe {JOURNAL}")

    trades = pd.read_csv(TRADES)
    journal = pd.read_csv(JOURNAL)

    if trades.empty:
        raise RuntimeError("paper_trades.csv está vacío.")

    if journal.empty:
        raise RuntimeError("candidate_journal.csv está vacío.")

    trades = trades.copy()
    journal = journal.copy()

    trades["opened_at_dt"] = pd.to_datetime(trades["opened_at"], errors="coerce", utc=True)
    trades["closed_at_dt"] = pd.to_datetime(trades["closed_at"], errors="coerce", utc=True)

    journal["observed_at_dt"] = pd.to_datetime(journal["observed_at"], errors="coerce", utc=True)
    journal = journal.dropna(subset=["observed_at_dt"])

    for col in ["best_bid", "best_ask", "spread", "score", "fair_edge_to_ask"]:
        if col in journal.columns:
            journal[col] = pd.to_numeric(journal[col], errors="coerce")

    return trades, journal


def matching_journal_rows(trade: pd.Series, journal: pd.DataFrame, max_replay_minutes: int) -> pd.DataFrame:
    symbol = safe_str(trade.get("crypto_symbol")).strip().upper()
    outcome = safe_str(trade.get("outcome")).strip()
    question = safe_str(trade.get("question")).strip()
    opened_at = trade.get("opened_at_dt")

    if pd.isna(opened_at):
        return pd.DataFrame()

    end_at = opened_at + pd.Timedelta(minutes=max_replay_minutes)

    rows = journal[
        journal["crypto_symbol"].astype(str).str.upper().eq(symbol)
        & journal["outcome"].astype(str).eq(outcome)
        & journal["question"].astype(str).eq(question)
        & (journal["observed_at_dt"] >= opened_at)
        & (journal["observed_at_dt"] <= end_at)
    ].copy()

    return rows.sort_values("observed_at_dt").reset_index(drop=True)


def pnl_values(entry_price: float, exit_bid: float, trade_usd: float) -> tuple[float, float]:
    if entry_price <= 0:
        return 0.0, 0.0

    shares = trade_usd / entry_price
    pnl_usd = shares * (exit_bid - entry_price)
    pnl_pct = ((exit_bid - entry_price) / entry_price) * 100

    return pnl_usd, pnl_pct


def bad_alignment(row: pd.Series) -> bool:
    alignment = safe_str(row.get("crypto_alignment")).strip().upper()
    decision = safe_str(row.get("crypto_decision")).strip()

    return (
        alignment in {"NEUTRAL", "CONFLICT"}
        or decision in {
            "CRYPTO_WAIT_BINANCE_NOT_ALIGNED",
            "CRYPTO_AVOID_BINANCE_CONFLICT",
        }
    )


def simulate_trade(
    trade: pd.Series,
    rows: pd.DataFrame,
    neutral_cycles: int,
    conflict_cycles: int,
    neutral_min_hold: int,
    conflict_min_hold: int,
    neutral_pnl_below: float,
    conflict_pnl_below: float,
    hard_stop_pct: float,
    soft_stop_pct: float,
    soft_stop_min_hold: int,
    soft_require_bad_alignment: bool,
    trailing_activate_pct: float,
    trailing_floor_pct: float,
    time_exit_minutes: int,
    time_exit_min_pnl_pct: float,
    max_replay_minutes: int,
) -> dict:
    entry_price = safe_float(trade.get("entry_price"))
    trade_usd = safe_float(trade.get("trade_usd"), 10.0)
    take_profit_price = safe_float(trade.get("take_profit_price"))
    opened_at = trade.get("opened_at_dt")

    original_close_reason = safe_str(trade.get("close_reason"))
    original_exit_bid = safe_float(trade.get("current_bid"))
    original_pnl_usd = safe_float(trade.get("pnl_usd"))
    original_pnl_pct = safe_float(trade.get("pnl_pct"))

    base = {
        "crypto_symbol": safe_str(trade.get("crypto_symbol")).strip().upper(),
        "outcome": safe_str(trade.get("outcome")).strip(),
        "question": safe_str(trade.get("question")).strip(),
        "entry_price": entry_price,
        "trade_usd": trade_usd,
        "original_close_reason": original_close_reason,
        "original_exit_bid": original_exit_bid,
        "original_pnl_usd": original_pnl_usd,
        "original_pnl_pct": original_pnl_pct,
        "neutral_cycles": neutral_cycles,
        "conflict_cycles": conflict_cycles,
        "neutral_min_hold": neutral_min_hold,
        "conflict_min_hold": conflict_min_hold,
        "neutral_pnl_below": neutral_pnl_below,
        "conflict_pnl_below": conflict_pnl_below,
        "hard_stop_pct": hard_stop_pct,
        "soft_stop_pct": soft_stop_pct,
        "soft_stop_min_hold": soft_stop_min_hold,
        "soft_require_bad_alignment": soft_require_bad_alignment,
        "trailing_activate_pct": trailing_activate_pct,
        "trailing_floor_pct": trailing_floor_pct,
        "time_exit_minutes": time_exit_minutes,
        "time_exit_min_pnl_pct": time_exit_min_pnl_pct,
        "max_replay_minutes": max_replay_minutes,
    }

    if entry_price is None or entry_price <= 0 or pd.isna(opened_at):
        base.update({
            "sim_exit_reason": "INVALID_TRADE",
            "sim_exit_bid": original_exit_bid,
            "sim_pnl_usd": original_pnl_usd,
            "sim_pnl_pct": original_pnl_pct,
            "sim_minutes_open": None,
            "journal_points": 0,
            "max_seen_pnl_pct": None,
            "last_alignment": "",
            "last_decision": "",
        })
        return base

    if rows.empty:
        base.update({
            "sim_exit_reason": "NO_JOURNAL_ROWS",
            "sim_exit_bid": original_exit_bid,
            "sim_pnl_usd": original_pnl_usd,
            "sim_pnl_pct": original_pnl_pct,
            "sim_minutes_open": None,
            "journal_points": 0,
            "max_seen_pnl_pct": None,
            "last_alignment": "",
            "last_decision": "",
        })
        return base

    neutral_streak = 0
    conflict_streak = 0
    max_seen_pnl_pct = -999999.0

    last_seen_bid = None
    last_seen_at = None
    last_alignment = ""
    last_decision = ""

    for _, row in rows.iterrows():
        bid = safe_float(row.get("best_bid"))

        if bid is None:
            continue

        observed_at = row["observed_at_dt"]
        age_minutes = (observed_at - opened_at).total_seconds() / 60
        pnl_usd, pnl_pct = pnl_values(entry_price, bid, trade_usd)

        max_seen_pnl_pct = max(max_seen_pnl_pct, pnl_pct)

        alignment = safe_str(row.get("crypto_alignment")).strip().upper()
        decision = safe_str(row.get("crypto_decision")).strip()

        last_seen_bid = bid
        last_seen_at = observed_at
        last_alignment = alignment
        last_decision = decision

        if alignment == "CONFLICT":
            conflict_streak += 1
            neutral_streak = 0
        elif alignment == "NEUTRAL":
            neutral_streak += 1
            conflict_streak = 0
        elif alignment == "ALIGNED":
            neutral_streak = 0
            conflict_streak = 0

        # 1. Take profit original.
        if take_profit_price is not None and bid >= take_profit_price:
            reason = "TAKE_PROFIT"

        # 2. Hard stop catastrófico.
        elif pnl_pct <= hard_stop_pct:
            reason = "HARD_STOP"

        # 3. Riesgo por CONFLICT.
        elif (
            conflict_streak >= conflict_cycles
            and age_minutes >= conflict_min_hold
            and pnl_pct <= conflict_pnl_below
        ):
            reason = "RISK_EXIT_CONFLICT"

        # 4. Riesgo por NEUTRAL.
        elif (
            neutral_streak >= neutral_cycles
            and age_minutes >= neutral_min_hold
            and pnl_pct <= neutral_pnl_below
        ):
            reason = "RISK_EXIT_NEUTRAL"

        # 5. Soft stop con confirmación.
        elif (
            pnl_pct <= soft_stop_pct
            and age_minutes >= soft_stop_min_hold
            and (not soft_require_bad_alignment or bad_alignment(row))
        ):
            reason = "SOFT_STOP"

        # 6. Trailing stop, solo después de ganancia.
        elif (
            max_seen_pnl_pct >= trailing_activate_pct
            and pnl_pct <= trailing_floor_pct
        ):
            reason = "TRAILING_STOP"

        # 7. Time exit para tomar ganancia y reducir exposición.
        elif (
            time_exit_minutes > 0
            and age_minutes >= time_exit_minutes
            and pnl_pct >= time_exit_min_pnl_pct
        ):
            reason = "TIME_EXIT"

        else:
            reason = ""

        if reason:
            base.update({
                "sim_exit_reason": reason,
                "sim_exit_bid": bid,
                "sim_pnl_usd": pnl_usd,
                "sim_pnl_pct": pnl_pct,
                "sim_minutes_open": age_minutes,
                "journal_points": len(rows),
                "max_seen_pnl_pct": max_seen_pnl_pct,
                "last_alignment": alignment,
                "last_decision": decision,
            })
            return base

    if last_seen_bid is None:
        last_seen_bid = original_exit_bid
        pnl_usd = original_pnl_usd
        pnl_pct = original_pnl_pct
        age_minutes = None
    else:
        pnl_usd, pnl_pct = pnl_values(entry_price, last_seen_bid, trade_usd)
        age_minutes = (last_seen_at - opened_at).total_seconds() / 60 if last_seen_at is not None else None

    base.update({
        "sim_exit_reason": "HORIZON",
        "sim_exit_bid": last_seen_bid,
        "sim_pnl_usd": pnl_usd,
        "sim_pnl_pct": pnl_pct,
        "sim_minutes_open": age_minutes,
        "journal_points": len(rows),
        "max_seen_pnl_pct": max_seen_pnl_pct,
        "last_alignment": last_alignment,
        "last_decision": last_decision,
    })
    return base


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    group_cols = [
        "neutral_cycles",
        "conflict_cycles",
        "neutral_min_hold",
        "conflict_min_hold",
        "neutral_pnl_below",
        "conflict_pnl_below",
        "hard_stop_pct",
        "soft_stop_pct",
        "soft_stop_min_hold",
        "soft_require_bad_alignment",
        "trailing_activate_pct",
        "trailing_floor_pct",
        "time_exit_minutes",
        "time_exit_min_pnl_pct",
        "max_replay_minutes",
    ]

    rows = []

    for key, group in results.groupby(group_cols, dropna=False):
        item = dict(zip(group_cols, key))

        item.update({
            "trades": len(group),
            "sim_total_pnl_usd": group["sim_pnl_usd"].sum(),
            "sim_avg_pnl_pct": group["sim_pnl_pct"].mean(),
            "sim_median_pnl_pct": group["sim_pnl_pct"].median(),
            "sim_win_rate": (group["sim_pnl_usd"] > 0).mean() * 100,
            "original_total_pnl_usd": group["original_pnl_usd"].sum(),
            "delta_vs_original_usd": group["sim_pnl_usd"].sum() - group["original_pnl_usd"].sum(),
            "avg_minutes_open": group["sim_minutes_open"].mean(),
            "hard_stop_count": int((group["sim_exit_reason"] == "HARD_STOP").sum()),
            "soft_stop_count": int((group["sim_exit_reason"] == "SOFT_STOP").sum()),
            "risk_conflict_count": int((group["sim_exit_reason"] == "RISK_EXIT_CONFLICT").sum()),
            "risk_neutral_count": int((group["sim_exit_reason"] == "RISK_EXIT_NEUTRAL").sum()),
            "trailing_stop_count": int((group["sim_exit_reason"] == "TRAILING_STOP").sum()),
            "time_exit_count": int((group["sim_exit_reason"] == "TIME_EXIT").sum()),
            "take_profit_count": int((group["sim_exit_reason"] == "TAKE_PROFIT").sum()),
            "horizon_count": int((group["sim_exit_reason"] == "HORIZON").sum()),
            "no_journal_rows_count": int((group["sim_exit_reason"] == "NO_JOURNAL_ROWS").sum()),
        })

        rows.append(item)

    summary = pd.DataFrame(rows)

    if summary.empty:
        return summary

    return summary.sort_values(
        ["delta_vs_original_usd", "sim_total_pnl_usd", "sim_win_rate"],
        ascending=[False, False, False],
    )


def main() -> None:
    print("\n=== PAPER COMBINED EXIT REPLAY ===")

    trades, journal = load_data()

    closed = trades[trades["status"].astype(str).eq("CLOSED")].copy()
    closed = closed[closed["opened_at_dt"].notna()]

    if closed.empty:
        print("No hay trades cerrados para simular.")
        return

    neutral_cycles_values = parse_int_csv("COMBINED_NEUTRAL_CYCLES", "2")
    conflict_cycles_values = parse_int_csv("COMBINED_CONFLICT_CYCLES", "1")
    neutral_min_hold_values = parse_int_csv("COMBINED_NEUTRAL_MIN_HOLD", "10")
    conflict_min_hold_values = parse_int_csv("COMBINED_CONFLICT_MIN_HOLD", "5")
    neutral_pnl_below_values = parse_float_csv("COMBINED_NEUTRAL_PNL_BELOW", "-5")
    conflict_pnl_below_values = parse_float_csv("COMBINED_CONFLICT_PNL_BELOW", "-2,-3.5,-4")

    hard_stop_values = parse_float_csv("COMBINED_HARD_STOP_VALUES", "-25,-30")
    soft_stop_values = parse_float_csv("COMBINED_SOFT_STOP_VALUES", "-6,-8")
    soft_min_hold_values = parse_int_csv("COMBINED_SOFT_MIN_HOLD_VALUES", "5,10")
    trailing_activate_values = parse_float_csv("COMBINED_TRAILING_ACTIVATE_VALUES", "10,15")
    trailing_floor_values = parse_float_csv("COMBINED_TRAILING_FLOOR_VALUES", "3,5")
    time_exit_minutes_values = parse_int_csv("COMBINED_TIME_EXIT_MINUTES_VALUES", "60,90")
    time_exit_min_pnl_values = parse_float_csv("COMBINED_TIME_EXIT_MIN_PNL_VALUES", "3,5")
    max_replay_minutes_values = parse_int_csv("COMBINED_MAX_MINUTES", "180")

    soft_require_bad_alignment = os.getenv("COMBINED_SOFT_REQUIRE_BAD_ALIGNMENT", "1") == "1"

    print(f"Trades cerrados: {len(closed)}")
    print(f"Original PnL total: ${closed['pnl_usd'].sum():.4f}")
    print(f"Soft requiere mala alineación: {soft_require_bad_alignment}")

    rows = []

    for combo in itertools.product(
        neutral_cycles_values,
        conflict_cycles_values,
        neutral_min_hold_values,
        conflict_min_hold_values,
        neutral_pnl_below_values,
        conflict_pnl_below_values,
        hard_stop_values,
        soft_stop_values,
        soft_min_hold_values,
        trailing_activate_values,
        trailing_floor_values,
        time_exit_minutes_values,
        time_exit_min_pnl_values,
        max_replay_minutes_values,
    ):
        (
            neutral_cycles,
            conflict_cycles,
            neutral_min_hold,
            conflict_min_hold,
            neutral_pnl_below,
            conflict_pnl_below,
            hard_stop_pct,
            soft_stop_pct,
            soft_stop_min_hold,
            trailing_activate_pct,
            trailing_floor_pct,
            time_exit_minutes,
            time_exit_min_pnl_pct,
            max_replay_minutes,
        ) = combo

        for _, trade in closed.iterrows():
            rows_for_trade = matching_journal_rows(trade, journal, max_replay_minutes)

            rows.append(
                simulate_trade(
                    trade=trade,
                    rows=rows_for_trade,
                    neutral_cycles=neutral_cycles,
                    conflict_cycles=conflict_cycles,
                    neutral_min_hold=neutral_min_hold,
                    conflict_min_hold=conflict_min_hold,
                    neutral_pnl_below=neutral_pnl_below,
                    conflict_pnl_below=conflict_pnl_below,
                    hard_stop_pct=hard_stop_pct,
                    soft_stop_pct=soft_stop_pct,
                    soft_stop_min_hold=soft_stop_min_hold,
                    soft_require_bad_alignment=soft_require_bad_alignment,
                    trailing_activate_pct=trailing_activate_pct,
                    trailing_floor_pct=trailing_floor_pct,
                    time_exit_minutes=time_exit_minutes,
                    time_exit_min_pnl_pct=time_exit_min_pnl_pct,
                    max_replay_minutes=max_replay_minutes,
                )
            )

    results = pd.DataFrame(rows)

    if results.empty:
        print("No hubo resultados simulados.")
        return

    OUT.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(OUT, index=False)

    summary = summarize(results)
    summary.to_csv(SUMMARY_OUT, index=False)

    print(f"Archivo detalle: {OUT}")
    print(f"Archivo resumen: {SUMMARY_OUT}")

    cols = [
        "trades",
        "sim_total_pnl_usd",
        "original_total_pnl_usd",
        "delta_vs_original_usd",
        "sim_avg_pnl_pct",
        "sim_median_pnl_pct",
        "sim_win_rate",
        "avg_minutes_open",
        "risk_conflict_count",
        "risk_neutral_count",
        "hard_stop_count",
        "soft_stop_count",
        "trailing_stop_count",
        "time_exit_count",
        "take_profit_count",
        "horizon_count",
        "no_journal_rows_count",
        "neutral_cycles",
        "conflict_cycles",
        "neutral_min_hold",
        "conflict_min_hold",
        "neutral_pnl_below",
        "conflict_pnl_below",
        "hard_stop_pct",
        "soft_stop_pct",
        "soft_stop_min_hold",
        "trailing_activate_pct",
        "trailing_floor_pct",
        "time_exit_minutes",
        "time_exit_min_pnl_pct",
    ]

    print("\n=== TOP POLÍTICAS COMBINADAS ===")
    print(summary[cols].head(30).to_string(index=False))

    best = summary.iloc[0]

    mask = pd.Series(True, index=results.index)

    for col in [
        "neutral_cycles",
        "conflict_cycles",
        "neutral_min_hold",
        "conflict_min_hold",
        "neutral_pnl_below",
        "conflict_pnl_below",
        "hard_stop_pct",
        "soft_stop_pct",
        "soft_stop_min_hold",
        "trailing_activate_pct",
        "trailing_floor_pct",
        "time_exit_minutes",
        "time_exit_min_pnl_pct",
    ]:
        mask &= results[col].eq(best[col])

    best_details = results[mask].copy()

    detail_cols = [
        "crypto_symbol",
        "outcome",
        "entry_price",
        "original_close_reason",
        "original_exit_bid",
        "original_pnl_usd",
        "original_pnl_pct",
        "sim_exit_reason",
        "sim_exit_bid",
        "sim_pnl_usd",
        "sim_pnl_pct",
        "max_seen_pnl_pct",
        "sim_minutes_open",
        "last_alignment",
        "last_decision",
        "question",
    ]

    print("\n=== DETALLE MEJOR POLÍTICA COMBINADA ===")
    print(best_details[detail_cols].to_string(index=False))


if __name__ == "__main__":
    main()
