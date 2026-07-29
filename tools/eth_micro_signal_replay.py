from __future__ import annotations

from pathlib import Path
from itertools import product
import os

import pandas as pd


JOURNAL_PATH = Path(os.getenv("REPLAY_CANDIDATE_JOURNAL", "data/candidate_journal.csv"))

OUT_SUMMARY = Path("data/eth_micro_signal_replay_summary.csv")
OUT_TRADES = Path("data/eth_micro_signal_replay_trades.csv")
OUT_TXT = Path("data/eth_micro_signal_replay.txt")

SYMBOL = os.getenv("REPLAY_SYMBOL", "ETHUSDT")
OUTCOME = os.getenv("REPLAY_OUTCOME", "Yes").lower()

TRADE_USD = float(os.getenv("REPLAY_TRADE_USD", "2"))
TP_PCT = float(os.getenv("REPLAY_TP_PCT", "4"))
SL_PCT = float(os.getenv("REPLAY_SL_PCT", "8"))
MAX_HOLD_MINUTES = float(os.getenv("REPLAY_MAX_HOLD_MINUTES", "180"))
MAX_NEW_PER_CYCLE = int(os.getenv("REPLAY_MAX_NEW_PER_CYCLE", "1"))

EDGE_VALUES = [float(x) for x in os.getenv("REPLAY_EDGE_VALUES", "0.15,0.20,0.25,0.30").split(",")]
MAX_OPEN_VALUES = [int(x) for x in os.getenv("REPLAY_MAX_OPEN_VALUES", "1,2").split(",")]
COOLDOWN_VALUES = [int(x) for x in os.getenv("REPLAY_COOLDOWN_VALUES", "180,90,60").split(",")]


def to_dt(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True, errors="coerce")


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def cooldown_key(row: pd.Series | dict) -> str:
    return f'{row.get("question", "")}|{str(row.get("outcome", "")).lower()}'


def load_journal() -> pd.DataFrame:
    if not JOURNAL_PATH.exists():
        raise SystemExit(f"No existe {JOURNAL_PATH}")

    df = pd.read_csv(JOURNAL_PATH)
    df["observed_at_dt"] = to_dt(df["observed_at"])

    for col in ["best_bid", "best_ask", "spread", "score", "fair_edge_to_ask"]:
        if col in df.columns:
            df[col] = num(df[col])

    return df.sort_values("observed_at_dt").reset_index(drop=True)


def filter_setups(df: pd.DataFrame, min_edge: float) -> pd.DataFrame:
    return df[
        (df["crypto_symbol"].astype(str).str.upper() == SYMBOL.upper())
        & (df["outcome"].astype(str).str.lower() == OUTCOME)
        & (df["crypto_decision"] == "CRYPTO_BUY_FAIR_EDGE")
        & (df["crypto_alignment"] == "ALIGNED")
        & (df["flow_bias"] == "BULLISH")
        & (df["score"] >= 80)
        & (df["fair_edge_to_ask"] >= min_edge)
        & (df["spread"] <= 0.01)
        & (df["best_ask"] >= 0.50)
        & (df["best_ask"] <= 0.60)
    ].copy()


def find_mark(tick: pd.DataFrame, pos: dict) -> pd.Series | None:
    same = tick[
        (tick["signal_key"].astype(str) == str(pos["signal_key"]))
        | (tick["token_id"].astype(str) == str(pos["token_id"]))
        | (
            (tick["question"].astype(str) == str(pos["question"]))
            & (tick["outcome"].astype(str).str.lower() == str(pos["outcome"]).lower())
        )
    ].dropna(subset=["best_bid"])

    if same.empty:
        return None

    return same.iloc[-1]


def close_pos(pos: dict, now, exit_price: float, reason: str) -> dict:
    pos = pos.copy()
    pos["status"] = "CLOSED"
    pos["exit_time"] = now.isoformat()
    pos["exit_price"] = exit_price
    pos["current_bid"] = exit_price
    pos["current_value_usd"] = pos["quantity"] * exit_price
    pos["pnl_usd"] = pos["quantity"] * (exit_price - pos["entry_price"])
    pos["pnl_pct"] = ((exit_price - pos["entry_price"]) / pos["entry_price"]) * 100
    pos["close_reason"] = reason
    return pos


def update_open(open_positions: list[dict], tick: pd.DataFrame, now) -> tuple[list[dict], list[dict]]:
    still_open = []
    closed = []

    for pos in open_positions:
        mark = find_mark(tick, pos)

        if mark is not None:
            pos["current_bid"] = float(mark["best_bid"])
            pos["current_ask"] = mark.get("best_ask")

        bid = pos.get("current_bid", pos["entry_bid"])
        age = (now - pos["entry_time_dt"]).total_seconds() / 60
        pnl_pct = ((bid - pos["entry_price"]) / pos["entry_price"]) * 100

        if pnl_pct >= TP_PCT:
            closed.append(close_pos(pos, now, bid, "MICRO_TAKE_PROFIT"))
        elif pnl_pct <= -SL_PCT:
            closed.append(close_pos(pos, now, bid, "MICRO_STOP_LOSS"))
        elif age >= MAX_HOLD_MINUTES:
            closed.append(close_pos(pos, now, bid, "MICRO_TIME_EXIT"))
        else:
            pos["pnl_pct"] = pnl_pct
            pos["pnl_usd"] = pos["quantity"] * (bid - pos["entry_price"])
            pos["current_value_usd"] = pos["quantity"] * bid
            still_open.append(pos)

    return still_open, closed


def make_trade(row: pd.Series, combo_id: str, trade_no: int) -> dict:
    entry = float(row["best_ask"])
    bid = float(row["best_bid"])
    qty = TRADE_USD / entry
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
        "entry_price": entry,
        "entry_bid": bid,
        "entry_ask": entry,
        "current_bid": bid,
        "current_ask": entry,
        "exit_price": pd.NA,
        "trade_usd": TRADE_USD,
        "quantity": qty,
        "current_value_usd": qty * bid,
        "pnl_usd": qty * (bid - entry),
        "pnl_pct": ((bid - entry) / entry) * 100,
        "entry_score": row.get("score", pd.NA),
        "entry_edge": row.get("fair_edge_to_ask", pd.NA),
        "entry_flow_bias": row.get("flow_bias", ""),
        "close_reason": "",
        "cooldown_key": cooldown_key(row),
    }


def simulate(df: pd.DataFrame, setups: pd.DataFrame, max_open: int, cooldown_minutes: int, min_edge: float) -> pd.DataFrame:
    combo_id = f"{SYMBOL}_edge{min_edge}_maxopen{max_open}_cooldown{cooldown_minutes}"

    event_times = df["observed_at_dt"].dropna().drop_duplicates().sort_values().tolist()
    setups_by_time = {t: part.copy() for t, part in setups.groupby("observed_at_dt")}

    open_positions = []
    closed_positions = []
    last_entry_by_key = {}
    trade_no = 0

    for now in event_times:
        tick = df[df["observed_at_dt"] == now].copy()
        open_positions, closed = update_open(open_positions, tick, now)
        closed_positions.extend(closed)

        candidates = setups_by_time.get(now)
        if candidates is None or candidates.empty:
            continue

        opened_this_cycle = 0

        candidates = candidates.sort_values(
            ["fair_edge_to_ask", "score"],
            ascending=[False, False],
            na_position="last",
        )

        for _, row in candidates.iterrows():
            key = cooldown_key(row)

            if len(open_positions) >= max_open:
                continue

            if opened_this_cycle >= MAX_NEW_PER_CYCLE:
                continue

            last_entry = last_entry_by_key.get(key)
            if last_entry is not None:
                minutes = (now - last_entry).total_seconds() / 60
                if 0 <= minutes <= cooldown_minutes:
                    continue

            trade_no += 1
            trade = make_trade(row, combo_id, trade_no)
            open_positions.append(trade)
            last_entry_by_key[key] = now
            opened_this_cycle += 1

    all_trades = closed_positions + open_positions
    return pd.DataFrame(all_trades)


def summarize(trades: pd.DataFrame, combo_id: str, max_open: int, cooldown: int, edge: float, setups_count: int) -> dict:
    if trades.empty:
        return {
            "combo_id": combo_id,
            "symbol": SYMBOL,
            "min_edge": edge,
            "max_open": max_open,
            "cooldown_minutes": cooldown,
            "setups": setups_count,
            "trades": 0,
            "closed": 0,
            "open": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_closed_pct": 0.0,
            "pnl_total_usd": 0.0,
            "take_profits": 0,
            "stop_losses": 0,
            "time_exits": 0,
        }

    closed = trades[trades["status"] == "CLOSED"].copy()
    wins = int((closed["pnl_usd"] > 0).sum()) if not closed.empty else 0
    losses = int((closed["pnl_usd"] < 0).sum()) if not closed.empty else 0
    win_rate = wins / len(closed) * 100 if len(closed) else 0.0

    return {
        "combo_id": combo_id,
        "symbol": SYMBOL,
        "min_edge": edge,
        "max_open": max_open,
        "cooldown_minutes": cooldown,
        "setups": setups_count,
        "trades": len(trades),
        "closed": len(closed),
        "open": int((trades["status"] == "OPEN").sum()),
        "wins": wins,
        "losses": losses,
        "win_rate_closed_pct": round(win_rate, 2),
        "pnl_total_usd": round(float(trades["pnl_usd"].sum()), 6),
        "avg_pnl_pct_closed": round(float(closed["pnl_pct"].mean()), 6) if len(closed) else 0.0,
        "take_profits": int((closed["close_reason"] == "MICRO_TAKE_PROFIT").sum()) if len(closed) else 0,
        "stop_losses": int((closed["close_reason"] == "MICRO_STOP_LOSS").sum()) if len(closed) else 0,
        "time_exits": int((closed["close_reason"] == "MICRO_TIME_EXIT").sum()) if len(closed) else 0,
    }


def main() -> None:
    df = load_journal()

    print("\n=== ETH MICRO SIGNAL REPLAY ===")
    print(f"Journal: {JOURNAL_PATH}")
    print(f"Symbol: {SYMBOL}")
    print(f"TP/SL: +{TP_PCT}% / -{SL_PCT}%")
    print(f"Max hold: {MAX_HOLD_MINUTES} min")
    print(f"Trade USD: ${TRADE_USD}")

    summaries = []
    all_trades = []

    for edge, max_open, cooldown in product(EDGE_VALUES, MAX_OPEN_VALUES, COOLDOWN_VALUES):
        setups = filter_setups(df, edge)
        trades = simulate(df, setups, max_open, cooldown, edge)
        combo_id = f"{SYMBOL}_edge{edge}_maxopen{max_open}_cooldown{cooldown}"

        summaries.append(
            summarize(trades, combo_id, max_open, cooldown, edge, len(setups))
        )

        if not trades.empty:
            all_trades.append(trades)

    summary = pd.DataFrame(summaries).sort_values(
        ["pnl_total_usd", "closed", "win_rate_closed_pct"],
        ascending=[False, False, False],
    )

    trades_out = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()

    summary.to_csv(OUT_SUMMARY, index=False)
    trades_out.to_csv(OUT_TRADES, index=False)

    with OUT_TXT.open("w") as f:
        f.write("=== ETH MICRO SIGNAL REPLAY ===\n")
        f.write(f"Journal: {JOURNAL_PATH}\n")
        f.write(f"Symbol: {SYMBOL}\n")
        f.write(f"TP/SL: +{TP_PCT}% / -{SL_PCT}%\n")
        f.write(f"Max hold: {MAX_HOLD_MINUTES} min\n")
        f.write(f"Trade USD: ${TRADE_USD}\n\n")
        f.write("=== SUMMARY ===\n")
        f.write(summary.to_string(index=False))
        f.write("\n")

    print("\n=== SUMMARY ===")
    print(summary.to_string(index=False))

    print("\nArchivos:")
    print(OUT_SUMMARY)
    print(OUT_TRADES)
    print(OUT_TXT)


if __name__ == "__main__":
    main()
