from __future__ import annotations

from pathlib import Path
from itertools import product
import os

import pandas as pd


JOURNAL_PATH = Path(os.getenv("CANDIDATE_JOURNAL_PATH", "data/candidate_journal.csv"))
TRADES_PATH = Path(os.getenv("MICRO_TPSL_TRADES_PATH", "data/micro_tpsl_paper_trades.csv"))

OUT_SUMMARY = Path("data/micro_capacity_replay_summary.csv")
OUT_TRADES = Path("data/micro_capacity_replay_trades.csv")
OUT_SKIPS = Path("data/micro_capacity_replay_skips.csv")
OUT_TXT = Path("data/micro_capacity_replay.txt")

TRADE_USD = float(os.getenv("MICRO_TPSL_TRADE_USD", "2"))
TP_PCT = float(os.getenv("MICRO_TPSL_TAKE_PROFIT_PCT", "4"))
SL_PCT = float(os.getenv("MICRO_TPSL_STOP_LOSS_PCT", "8"))
MAX_HOLD_MINUTES = float(os.getenv("MICRO_TPSL_MAX_HOLD_MINUTES", "180"))
MAX_NEW_PER_CYCLE = int(os.getenv("CAPACITY_MAX_NEW_PER_CYCLE", "1"))

MAX_OPEN_VALUES = [
    int(x.strip())
    for x in os.getenv("CAPACITY_MAX_OPEN_VALUES", "1,2,3").split(",")
    if x.strip()
]

COOLDOWN_VALUES = [
    int(x.strip())
    for x in os.getenv("CAPACITY_COOLDOWN_VALUES", "180,90,60").split(",")
    if x.strip()
]

START_AT_FIRST_RECORDED_TRADE = os.getenv("CAPACITY_START_AT_FIRST_TRADE", "1") == "1"

# Para evitar duplicar exposición en la misma pregunta aunque cambie token/signal_key.
# Opciones: question, signal
COOLDOWN_SCOPE = os.getenv("CAPACITY_COOLDOWN_SCOPE", "question")


def to_dt(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def cooldown_key(row: pd.Series | dict) -> str:
    if COOLDOWN_SCOPE == "signal":
        return str(row.get("signal_key", ""))

    return f'{row.get("question", "")}|{str(row.get("outcome", "")).lower()}'


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not JOURNAL_PATH.exists():
        raise SystemExit(f"No existe {JOURNAL_PATH}")

    journal = pd.read_csv(JOURNAL_PATH)
    trades = pd.read_csv(TRADES_PATH) if TRADES_PATH.exists() else pd.DataFrame()

    journal["observed_at_dt"] = to_dt(journal["observed_at"])

    for col in ["best_bid", "best_ask", "spread", "score", "fair_edge_to_ask"]:
        if col in journal.columns:
            journal[col] = num(journal[col])

    if not trades.empty:
        trades["entry_time_dt"] = to_dt(trades["entry_time"])
        trades["exit_time_dt"] = to_dt(trades["exit_time"])

    return journal, trades


def filter_micro_setups(journal: pd.DataFrame) -> pd.DataFrame:
    micro = journal[
        (journal["crypto_symbol"].astype(str).str.upper() == "BTCUSDT")
        & (journal["outcome"].astype(str).str.lower() == "yes")
        & (journal["crypto_decision"] == "CRYPTO_BUY_FAIR_EDGE")
        & (journal["crypto_alignment"] == "ALIGNED")
        & (journal["flow_bias"] == "BULLISH")
        & (journal["fair_edge_to_ask"] >= 0.30)
        & (journal["score"] >= 80)
        & (journal["spread"] <= 0.01)
        & (journal["best_ask"] >= 0.50)
        & (journal["best_ask"] <= 0.60)
    ].copy()

    return micro.sort_values("observed_at_dt").reset_index(drop=True)


def find_mark(tick: pd.DataFrame, pos: dict) -> pd.Series | None:
    same = tick[
        (tick["signal_key"].astype(str) == str(pos["signal_key"]))
        | (tick["token_id"].astype(str) == str(pos["token_id"]))
        | (
            (tick["question"].astype(str) == str(pos["question"]))
            & (tick["outcome"].astype(str).str.lower() == str(pos["outcome"]).lower())
        )
    ].copy()

    same = same.dropna(subset=["best_bid"])

    if same.empty:
        return None

    return same.iloc[-1]


def close_position(pos: dict, exit_time, exit_price: float, close_reason: str) -> dict:
    pnl_usd = pos["quantity"] * (exit_price - pos["entry_price"])
    pnl_pct = ((exit_price - pos["entry_price"]) / pos["entry_price"]) * 100

    pos = pos.copy()
    pos["status"] = "CLOSED"
    pos["exit_time"] = exit_time.isoformat()
    pos["exit_price"] = exit_price
    pos["current_bid"] = exit_price
    pos["current_value_usd"] = pos["quantity"] * exit_price
    pos["pnl_usd"] = pnl_usd
    pos["pnl_pct"] = pnl_pct
    pos["close_reason"] = close_reason

    return pos


def update_open_positions(open_positions: list[dict], tick: pd.DataFrame, now) -> tuple[list[dict], list[dict]]:
    still_open = []
    closed = []

    for pos in open_positions:
        mark = find_mark(tick, pos)

        if mark is not None:
            bid = float(mark["best_bid"])
            ask = mark.get("best_ask")
            pos["current_bid"] = bid
            pos["current_ask"] = ask
            pos["last_mark_time"] = now

        current_bid = pos.get("current_bid")
        if pd.isna(current_bid):
            current_bid = pos["entry_bid"]

        age_minutes = (now - pos["entry_time_dt"]).total_seconds() / 60
        pnl_pct = ((current_bid - pos["entry_price"]) / pos["entry_price"]) * 100

        reason = None

        # Replicamos la lógica del micro executor: TP/SL primero, tiempo después.
        if pnl_pct >= TP_PCT:
            reason = "MICRO_TAKE_PROFIT"
        elif pnl_pct <= -SL_PCT:
            reason = "MICRO_STOP_LOSS"
        elif age_minutes >= MAX_HOLD_MINUTES:
            reason = "MICRO_TIME_EXIT"

        if reason:
            closed.append(close_position(pos, now, float(current_bid), reason))
        else:
            pos["current_value_usd"] = pos["quantity"] * float(current_bid)
            pos["pnl_usd"] = pos["current_value_usd"] - pos["trade_usd"]
            pos["pnl_pct"] = pnl_pct
            still_open.append(pos)

    return still_open, closed


def make_trade(row: pd.Series, combo_id: str, trade_no: int) -> dict:
    entry_price = float(row["best_ask"])
    entry_bid = float(row["best_bid"])
    quantity = TRADE_USD / entry_price
    now = row["observed_at_dt"]

    return {
        "combo_id": combo_id,
        "trade_id": f"{combo_id}_trade_{trade_no:04d}",
        "status": "OPEN",
        "signal_key": row.get("signal_key", ""),
        "token_id": row.get("token_id", ""),
        "question": row.get("question", ""),
        "crypto_symbol": row.get("crypto_symbol", ""),
        "outcome": row.get("outcome", ""),
        "entry_time": now.isoformat(),
        "entry_time_dt": now,
        "exit_time": "",
        "entry_price": entry_price,
        "entry_bid": entry_bid,
        "entry_ask": entry_price,
        "current_bid": entry_bid,
        "current_ask": entry_price,
        "exit_price": pd.NA,
        "trade_usd": TRADE_USD,
        "quantity": quantity,
        "current_value_usd": quantity * entry_bid,
        "pnl_usd": quantity * (entry_bid - entry_price),
        "pnl_pct": ((entry_bid - entry_price) / entry_price) * 100,
        "take_profit_price": entry_price * (1 + TP_PCT / 100),
        "stop_loss_price": entry_price * (1 - SL_PCT / 100),
        "close_reason": "",
        "entry_score": row.get("score", pd.NA),
        "entry_edge": row.get("fair_edge_to_ask", pd.NA),
        "entry_spread": row.get("spread", pd.NA),
        "entry_flow_bias": row.get("flow_bias", ""),
        "entry_alignment": row.get("crypto_alignment", ""),
        "cooldown_key": cooldown_key(row),
    }


def simulate_combo(
    journal: pd.DataFrame,
    setups: pd.DataFrame,
    max_open: int,
    cooldown_minutes: int,
    start_time,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    combo_id = f"maxopen{max_open}_cooldown{cooldown_minutes}"

    j = journal.copy()
    s = setups.copy()

    if pd.notna(start_time):
        j = j[j["observed_at_dt"] >= start_time].copy()
        s = s[s["observed_at_dt"] >= start_time].copy()

    event_times = (
        j["observed_at_dt"]
        .dropna()
        .drop_duplicates()
        .sort_values()
        .tolist()
    )

    setups_by_time = {t: part.copy() for t, part in s.groupby("observed_at_dt")}
    last_entry_by_key: dict[str, pd.Timestamp] = {}

    open_positions: list[dict] = []
    closed_positions: list[dict] = []
    skips: list[dict] = []
    trade_no = 0

    for now in event_times:
        tick = j[j["observed_at_dt"] == now].copy()

        open_positions, newly_closed = update_open_positions(open_positions, tick, now)
        closed_positions.extend(newly_closed)

        candidates = setups_by_time.get(now)
        if candidates is None or candidates.empty:
            continue

        candidates = candidates.sort_values(
            ["fair_edge_to_ask", "score"],
            ascending=[False, False],
            na_position="last",
        )

        opened_this_cycle = 0

        for _, row in candidates.iterrows():
            key = cooldown_key(row)

            if len(open_positions) >= max_open:
                skips.append({
                    "combo_id": combo_id,
                    "observed_at": now.isoformat(),
                    "why_skipped": "BLOCKED_MAX_OPEN",
                    "question": row.get("question", ""),
                    "best_ask": row.get("best_ask", pd.NA),
                    "score": row.get("score", pd.NA),
                    "fair_edge_to_ask": row.get("fair_edge_to_ask", pd.NA),
                })
                continue

            if opened_this_cycle >= MAX_NEW_PER_CYCLE:
                skips.append({
                    "combo_id": combo_id,
                    "observed_at": now.isoformat(),
                    "why_skipped": "BLOCKED_MAX_NEW_PER_CYCLE",
                    "question": row.get("question", ""),
                    "best_ask": row.get("best_ask", pd.NA),
                    "score": row.get("score", pd.NA),
                    "fair_edge_to_ask": row.get("fair_edge_to_ask", pd.NA),
                })
                continue

            last_entry = last_entry_by_key.get(key)
            if last_entry is not None:
                minutes_since = (now - last_entry).total_seconds() / 60
                if 0 <= minutes_since <= cooldown_minutes:
                    skips.append({
                        "combo_id": combo_id,
                        "observed_at": now.isoformat(),
                        "why_skipped": "BLOCKED_COOLDOWN",
                        "cooldown_minutes": cooldown_minutes,
                        "minutes_since_entry": minutes_since,
                        "question": row.get("question", ""),
                        "best_ask": row.get("best_ask", pd.NA),
                        "score": row.get("score", pd.NA),
                        "fair_edge_to_ask": row.get("fair_edge_to_ask", pd.NA),
                    })
                    continue

            trade_no += 1
            trade = make_trade(row, combo_id, trade_no)
            open_positions.append(trade)
            last_entry_by_key[key] = now
            opened_this_cycle += 1

    if event_times:
        last_time = event_times[-1]
    else:
        last_time = pd.Timestamp.utcnow()

    final_positions = []
    for pos in open_positions:
        pos = pos.copy()
        pos["status"] = "OPEN"
        pos["exit_time"] = ""
        pos["exit_price"] = pd.NA
        final_positions.append(pos)

    all_trades = closed_positions + final_positions

    trades_df = pd.DataFrame(all_trades)
    skips_df = pd.DataFrame(skips)

    return trades_df, skips_df


def summarize(trades: pd.DataFrame, skips: pd.DataFrame, combo_id: str, max_open: int, cooldown: int) -> dict:
    if trades.empty:
        return {
            "combo_id": combo_id,
            "max_open": max_open,
            "cooldown_minutes": cooldown,
            "trades": 0,
            "closed": 0,
            "open": 0,
            "wins": 0,
            "losses": 0,
            "flats": 0,
            "win_rate_closed_pct": 0.0,
            "pnl_total_usd": 0.0,
            "pnl_closed_usd": 0.0,
            "avg_pnl_pct_closed": 0.0,
            "take_profits": 0,
            "stop_losses": 0,
            "time_exits": 0,
            "skipped_max_open": int((skips.get("why_skipped", pd.Series(dtype=str)) == "BLOCKED_MAX_OPEN").sum()),
            "skipped_cooldown": int((skips.get("why_skipped", pd.Series(dtype=str)) == "BLOCKED_COOLDOWN").sum()),
            "skipped_max_new_cycle": int((skips.get("why_skipped", pd.Series(dtype=str)) == "BLOCKED_MAX_NEW_PER_CYCLE").sum()),
        }

    closed = trades[trades["status"] == "CLOSED"].copy()
    open_ = trades[trades["status"] == "OPEN"].copy()

    wins = int((closed["pnl_usd"] > 0).sum()) if not closed.empty else 0
    losses = int((closed["pnl_usd"] < 0).sum()) if not closed.empty else 0
    flats = int((closed["pnl_usd"] == 0).sum()) if not closed.empty else 0

    win_rate = (wins / len(closed) * 100) if len(closed) else 0.0

    why = skips["why_skipped"] if not skips.empty and "why_skipped" in skips.columns else pd.Series(dtype=str)

    return {
        "combo_id": combo_id,
        "max_open": max_open,
        "cooldown_minutes": cooldown,
        "trades": len(trades),
        "closed": len(closed),
        "open": len(open_),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate_closed_pct": round(win_rate, 2),
        "pnl_total_usd": round(float(trades["pnl_usd"].sum()), 6),
        "pnl_closed_usd": round(float(closed["pnl_usd"].sum()), 6) if not closed.empty else 0.0,
        "avg_pnl_pct_closed": round(float(closed["pnl_pct"].mean()), 6) if not closed.empty else 0.0,
        "take_profits": int((closed["close_reason"] == "MICRO_TAKE_PROFIT").sum()) if not closed.empty else 0,
        "stop_losses": int((closed["close_reason"] == "MICRO_STOP_LOSS").sum()) if not closed.empty else 0,
        "time_exits": int((closed["close_reason"] == "MICRO_TIME_EXIT").sum()) if not closed.empty else 0,
        "skipped_max_open": int((why == "BLOCKED_MAX_OPEN").sum()),
        "skipped_cooldown": int((why == "BLOCKED_COOLDOWN").sum()),
        "skipped_max_new_cycle": int((why == "BLOCKED_MAX_NEW_PER_CYCLE").sum()),
    }


def main() -> None:
    journal, recorded_trades = load_data()
    setups = filter_micro_setups(journal)

    first_recorded_trade_time = pd.NaT
    if START_AT_FIRST_RECORDED_TRADE and not recorded_trades.empty:
        first_recorded_trade_time = recorded_trades["entry_time_dt"].min()

    setups_used = setups.copy()
    if pd.notna(first_recorded_trade_time):
        setups_used = setups_used[setups_used["observed_at_dt"] >= first_recorded_trade_time]

    print("\n=== MICRO CAPACITY REPLAY ===")
    print(f"Journal: {JOURNAL_PATH}")
    print(f"Micro trades actuales: {TRADES_PATH}")
    print(f"Setups micro exactos totales: {len(setups)}")
    print(f"Start at first recorded trade: {START_AT_FIRST_RECORDED_TRADE}")
    print(f"Start time usado: {first_recorded_trade_time}")
    print(f"Setups usados en replay: {len(setups_used)}")
    print(f"TP/SL: +{TP_PCT}% / -{SL_PCT}% | max hold: {MAX_HOLD_MINUTES} min")
    print(f"Trade USD: ${TRADE_USD:.2f} | max new/cycle: {MAX_NEW_PER_CYCLE}")
    print(f"Cooldown scope: {COOLDOWN_SCOPE}")

    all_summaries = []
    all_trades = []
    all_skips = []

    for max_open, cooldown in product(MAX_OPEN_VALUES, COOLDOWN_VALUES):
        combo_id = f"maxopen{max_open}_cooldown{cooldown}"
        trades, skips = simulate_combo(
            journal=journal,
            setups=setups,
            max_open=max_open,
            cooldown_minutes=cooldown,
            start_time=first_recorded_trade_time,
        )

        summary = summarize(trades, skips, combo_id, max_open, cooldown)
        all_summaries.append(summary)

        if not trades.empty:
            all_trades.append(trades)

        if not skips.empty:
            all_skips.append(skips)

    summary_df = pd.DataFrame(all_summaries).sort_values(
        ["pnl_total_usd", "closed", "win_rate_closed_pct"],
        ascending=[False, False, False],
    )

    trades_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    skips_df = pd.concat(all_skips, ignore_index=True) if all_skips else pd.DataFrame()

    summary_df.to_csv(OUT_SUMMARY, index=False)
    trades_df.to_csv(OUT_TRADES, index=False)
    skips_df.to_csv(OUT_SKIPS, index=False)

    with OUT_TXT.open("w") as f:
        f.write("=== MICRO CAPACITY REPLAY ===\n")
        f.write(f"Setups micro exactos totales: {len(setups)}\n")
        f.write(f"Setups usados en replay: {len(setups_used)}\n")
        f.write(f"Start time usado: {first_recorded_trade_time}\n")
        f.write(f"TP/SL: +{TP_PCT}% / -{SL_PCT}% | max hold: {MAX_HOLD_MINUTES} min\n")
        f.write(f"Trade USD: ${TRADE_USD:.2f} | max new/cycle: {MAX_NEW_PER_CYCLE}\n")
        f.write(f"Cooldown scope: {COOLDOWN_SCOPE}\n\n")
        f.write("=== SUMMARY ===\n")
        f.write(summary_df.to_string(index=False))
        f.write("\n\n")
        f.write(f"CSV summary: {OUT_SUMMARY}\n")
        f.write(f"CSV trades: {OUT_TRADES}\n")
        f.write(f"CSV skips: {OUT_SKIPS}\n")

    print("\n=== SUMMARY ===")
    print(summary_df.to_string(index=False))

    print("\nArchivos:")
    print(OUT_SUMMARY)
    print(OUT_TRADES)
    print(OUT_SKIPS)
    print(OUT_TXT)


if __name__ == "__main__":
    main()
