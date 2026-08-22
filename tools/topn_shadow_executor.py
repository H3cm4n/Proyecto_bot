from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import os
import uuid

import pandas as pd


SNAPSHOT_PATH = Path(os.getenv("TOPN_SNAPSHOT_PATH", "data/crypto_signal_snapshot_fair_value.csv"))
TRADES_PATH = Path(os.getenv("TOPN_TRADES_PATH", "data/topn_shadow_trades.csv"))

TRADE_USD = float(os.getenv("TOPN_TRADE_USD", "0.10"))
MAX_OPEN = int(os.getenv("TOPN_MAX_OPEN", "20"))
MAX_NEW_PER_CYCLE = int(os.getenv("TOPN_MAX_NEW_PER_CYCLE", "10"))

TP_PCT = float(os.getenv("TOPN_TAKE_PROFIT_PCT", "2"))
SL_PCT = float(os.getenv("TOPN_STOP_LOSS_PCT", "4"))
MAX_HOLD_MINUTES = float(os.getenv("TOPN_MAX_HOLD_MINUTES", "30"))
ENTRY_COOLDOWN_MINUTES = float(os.getenv("TOPN_ENTRY_COOLDOWN_MINUTES", "1"))

ALLOWED_SYMBOLS = {
    x.strip().upper()
    for x in os.getenv("TOPN_ALLOWED_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT").split(",")
    if x.strip()
}

ALLOWED_OUTCOMES = {
    x.strip().lower()
    for x in os.getenv("TOPN_ALLOWED_OUTCOMES", "Yes,No").split(",")
    if x.strip()
}

MIN_ASK = float(os.getenv("TOPN_MIN_ASK", "0.02"))
MAX_ASK = float(os.getenv("TOPN_MAX_ASK", "0.98"))
MAX_SPREAD = float(os.getenv("TOPN_MAX_SPREAD", "0.25"))
MIN_SCORE = float(os.getenv("TOPN_MIN_SCORE", "0"))
MIN_EDGE = float(os.getenv("TOPN_MIN_EDGE", "-999"))


COLUMNS = [
    "trade_id",
    "strategy",
    "status",
    "crypto_symbol",
    "outcome",
    "question",
    "signal_key",
    "token_id",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "current_bid",
    "current_ask",
    "trade_usd",
    "quantity",
    "current_value_usd",
    "pnl_usd",
    "pnl_pct",
    "entry_score",
    "entry_edge",
    "entry_decision",
    "entry_alignment",
    "entry_flow_bias",
    "latest_decision",
    "latest_alignment",
    "latest_flow_bias",
    "close_reason",
    "cooldown_key",
]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value):
    return pd.to_datetime(value, utc=True, errors="coerce")


def as_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def split_status(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df.empty or "status" not in df.columns:
        return pd.DataFrame(columns=COLUMNS), pd.DataFrame(columns=COLUMNS)

    open_df = df[df["status"].astype(str).str.upper() == "OPEN"].copy()
    closed_df = df[df["status"].astype(str).str.upper() != "OPEN"].copy()
    return open_df, closed_df


def cooldown_key(row) -> str:
    symbol = str(row.get("crypto_symbol", "")).upper()
    outcome = str(row.get("outcome", "")).lower()
    question = str(row.get("question", ""))
    return f"{symbol}|{outcome}|{question}"


def load_trades() -> pd.DataFrame:
    if not TRADES_PATH.exists():
        return pd.DataFrame(columns=COLUMNS)

    try:
        df = pd.read_csv(TRADES_PATH)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=COLUMNS)

    for col in COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    return df[COLUMNS].copy()


def save_trades(df: pd.DataFrame) -> None:
    TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)

    for col in COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    df[COLUMNS].to_csv(TRADES_PATH, index=False)


def load_snapshot() -> pd.DataFrame:
    if not SNAPSHOT_PATH.exists():
        raise SystemExit(f"No existe snapshot: {SNAPSHOT_PATH}")

    df = pd.read_csv(SNAPSHOT_PATH)

    text_cols = [
        "question",
        "outcome",
        "crypto_symbol",
        "crypto_decision",
        "crypto_alignment",
        "flow_bias",
        "signal_key",
        "token_id",
    ]

    for col in text_cols:
        if col not in df.columns:
            df[col] = ""

    for col in ["best_bid", "best_ask", "spread", "score", "fair_edge_to_ask"]:
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = as_num(df[col])

    if df["spread"].isna().all():
        df["spread"] = df["best_ask"] - df["best_bid"]

    df["rank_edge"] = df["fair_edge_to_ask"].fillna(-999)
    df["rank_score"] = df["score"].fillna(0)

    return df


def build_candidates(df: pd.DataFrame) -> pd.DataFrame:
    mask = (
        df["crypto_symbol"].astype(str).str.upper().isin(ALLOWED_SYMBOLS)
        & df["outcome"].astype(str).str.lower().isin(ALLOWED_OUTCOMES)
        & df["best_bid"].notna()
        & df["best_ask"].notna()
        & (df["best_bid"] > 0)
        & (df["best_ask"] > 0)
        & df["best_ask"].between(MIN_ASK, MAX_ASK, inclusive="both")
        & (df["spread"].fillna(999) <= MAX_SPREAD)
        & (df["rank_score"] >= MIN_SCORE)
        & (df["rank_edge"] >= MIN_EDGE)
    )

    c = df[mask].copy()

    if c.empty:
        return c

    decision = c["crypto_decision"].astype(str)
    alignment = c["crypto_alignment"].astype(str)
    flow = c["flow_bias"].astype(str)

    c["decision_rank"] = 0
    c.loc[decision.eq("CRYPTO_BUY_FAIR_EDGE"), "decision_rank"] = 5
    c.loc[decision.eq("CRYPTO_WATCH_FAIR_EDGE"), "decision_rank"] = 4
    c.loc[decision.str.contains("WAIT", na=False), "decision_rank"] = 2
    c.loc[decision.str.contains("AVOID", na=False), "decision_rank"] = 1
    c.loc[decision.str.contains("IGNORE", na=False), "decision_rank"] = 0

    c["alignment_rank"] = 0
    c.loc[alignment.eq("ALIGNED"), "alignment_rank"] = 2
    c.loc[alignment.eq("NEUTRAL"), "alignment_rank"] = 1

    c["flow_rank"] = 0
    c.loc[flow.isin(["BULLISH", "BEARISH"]), "flow_rank"] = 1

    c = c.sort_values(
        ["decision_rank", "alignment_rank", "flow_rank", "rank_edge", "rank_score", "spread"],
        ascending=[False, False, False, False, False, True],
        na_position="last",
    )

    return c


def find_mark(snapshot: pd.DataFrame, pos: dict):
    signal_key = str(pos.get("signal_key", ""))
    token_id = str(pos.get("token_id", ""))
    question = str(pos.get("question", ""))
    outcome = str(pos.get("outcome", "")).lower()
    symbol = str(pos.get("crypto_symbol", "")).upper()

    s_signal = snapshot["signal_key"].astype(str)
    s_token = snapshot["token_id"].astype(str)
    s_question = snapshot["question"].astype(str)
    s_outcome = snapshot["outcome"].astype(str).str.lower()
    s_symbol = snapshot["crypto_symbol"].astype(str).str.upper()

    same = snapshot[
        ((signal_key != "") & (s_signal == signal_key))
        | ((token_id != "") & (s_token == token_id))
        | ((s_question == question) & (s_outcome == outcome) & (s_symbol == symbol))
    ].dropna(subset=["best_bid"])

    if same.empty:
        return None

    return same.iloc[-1]


def close_position(pos: dict, exit_price: float, reason: str, now: datetime) -> dict:
    pos = pos.copy()
    entry_price = float(pos["entry_price"])
    quantity = float(pos["quantity"])

    pos["status"] = "CLOSED"
    pos["exit_time"] = now.isoformat()
    pos["exit_price"] = exit_price
    pos["current_bid"] = exit_price
    pos["current_value_usd"] = quantity * exit_price
    pos["pnl_usd"] = quantity * (exit_price - entry_price)
    pos["pnl_pct"] = ((exit_price - entry_price) / entry_price) * 100
    pos["close_reason"] = reason

    return pos


def update_open_positions(open_df: pd.DataFrame, snapshot: pd.DataFrame, now: datetime) -> tuple[list[dict], list[dict]]:
    still_open = []
    newly_closed = []

    if open_df.empty:
        return still_open, newly_closed

    for _, row in open_df.iterrows():
        pos = row.to_dict()
        entry_time = parse_dt(pos.get("entry_time"))
        entry_price = float(pos.get("entry_price", 0) or 0)

        if pd.isna(entry_time) or entry_price <= 0:
            pos["status"] = "CLOSED"
            pos["close_reason"] = "TOPN_BAD_POSITION_DATA"
            newly_closed.append(pos)
            continue

        mark = find_mark(snapshot, pos)

        if mark is not None:
            current_bid = float(mark["best_bid"])
            pos["current_bid"] = current_bid
            pos["current_ask"] = mark.get("best_ask", pd.NA)
            pos["latest_decision"] = mark.get("crypto_decision", "")
            pos["latest_alignment"] = mark.get("crypto_alignment", "")
            pos["latest_flow_bias"] = mark.get("flow_bias", "")
        else:
            current_bid = float(pos.get("current_bid", entry_price) or entry_price)

        age_min = (pd.Timestamp(now) - entry_time).total_seconds() / 60
        pnl_pct = ((current_bid - entry_price) / entry_price) * 100

        if pnl_pct >= TP_PCT:
            newly_closed.append(close_position(pos, current_bid, "TOPN_TAKE_PROFIT", now))
        elif pnl_pct <= -SL_PCT:
            newly_closed.append(close_position(pos, current_bid, "TOPN_STOP_LOSS", now))
        elif age_min >= MAX_HOLD_MINUTES:
            reason = "TOPN_TIME_EXIT" if mark is not None else "TOPN_TIME_EXIT_STALE"
            newly_closed.append(close_position(pos, current_bid, reason, now))
        else:
            quantity = float(pos.get("quantity", 0) or 0)
            pos["pnl_pct"] = pnl_pct
            pos["pnl_usd"] = quantity * (current_bid - entry_price)
            pos["current_value_usd"] = quantity * current_bid
            still_open.append(pos)

    return still_open, newly_closed


def build_last_entry_map(trades: pd.DataFrame) -> dict[str, pd.Timestamp]:
    out = {}

    if trades.empty or "cooldown_key" not in trades.columns:
        return out

    for _, row in trades.iterrows():
        key = str(row.get("cooldown_key", ""))
        ts = parse_dt(row.get("entry_time"))

        if not key or pd.isna(ts):
            continue

        old = out.get(key)
        if old is None or ts > old:
            out[key] = ts

    return out


def make_trade(row, now: datetime) -> dict:
    entry_price = float(row["best_ask"])
    current_bid = float(row["best_bid"])
    quantity = TRADE_USD / entry_price

    return {
        "trade_id": f"topn_{now.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}",
        "strategy": "TOPN_SHADOW_CASINO_LAB",
        "status": "OPEN",
        "crypto_symbol": str(row.get("crypto_symbol", "")),
        "outcome": str(row.get("outcome", "")),
        "question": str(row.get("question", "")),
        "signal_key": str(row.get("signal_key", "")),
        "token_id": str(row.get("token_id", "")),
        "entry_time": now.isoformat(),
        "exit_time": "",
        "entry_price": entry_price,
        "exit_price": pd.NA,
        "current_bid": current_bid,
        "current_ask": entry_price,
        "trade_usd": TRADE_USD,
        "quantity": quantity,
        "current_value_usd": quantity * current_bid,
        "pnl_usd": quantity * (current_bid - entry_price),
        "pnl_pct": ((current_bid - entry_price) / entry_price) * 100,
        "entry_score": row.get("score", pd.NA),
        "entry_edge": row.get("fair_edge_to_ask", pd.NA),
        "entry_decision": row.get("crypto_decision", ""),
        "entry_alignment": row.get("crypto_alignment", ""),
        "entry_flow_bias": row.get("flow_bias", ""),
        "latest_decision": row.get("crypto_decision", ""),
        "latest_alignment": row.get("crypto_alignment", ""),
        "latest_flow_bias": row.get("flow_bias", ""),
        "close_reason": "",
        "cooldown_key": cooldown_key(row),
    }


def print_status(trades: pd.DataFrame, candidates: pd.DataFrame, opened: list[dict], closed_now: list[dict]) -> None:
    print("\n=== TOPN SHADOW EXECUTION ===")
    print(f"Snapshot: {SNAPSHOT_PATH}")
    print(f"Trades file: {TRADES_PATH}")
    print(f"Trade USD: ${TRADE_USD:.2f}")
    print(f"Max open: {MAX_OPEN}")
    print(f"Max new/cycle: {MAX_NEW_PER_CYCLE}")
    print(f"TP/SL: +{TP_PCT:.2f}% / -{SL_PCT:.2f}%")
    print(f"Max hold: {MAX_HOLD_MINUTES} min")
    print(f"Cooldown: {ENTRY_COOLDOWN_MINUTES} min")
    print(f"Filtros: symbols={sorted(ALLOWED_SYMBOLS)} outcomes={sorted(ALLOWED_OUTCOMES)}")
    print(f"Ask {MIN_ASK}-{MAX_ASK}, spread <= {MAX_SPREAD}, score >= {MIN_SCORE}, edge >= {MIN_EDGE}")

    print("\nCandidatos disponibles:", len(candidates))
    print("Cerrados en este ciclo:", len(closed_now))
    print("Nuevas entradas:", len(opened))

    if opened:
        print("\nEntradas nuevas:")
        cols = [
            "crypto_symbol",
            "outcome",
            "entry_price",
            "current_bid",
            "pnl_pct",
            "entry_score",
            "entry_edge",
            "entry_decision",
            "entry_alignment",
            "entry_flow_bias",
            "question",
        ]
        print(pd.DataFrame(opened)[cols].to_string(index=False))

    if trades.empty:
        print("\nSin trades todavía.")
        return

    print("\nStatus:")
    print(trades["status"].value_counts(dropna=False).to_string())

    closed = trades[trades["status"] == "CLOSED"]
    wins = int((closed["pnl_usd"] > 0).sum()) if not closed.empty else 0
    losses = int((closed["pnl_usd"] < 0).sum()) if not closed.empty else 0
    win_rate = wins / len(closed) * 100 if len(closed) else 0

    print("\nPnL total:", round(float(trades["pnl_usd"].sum()), 6))
    print("Cerrados:", len(closed))
    print("Abiertos:", int((trades["status"] == "OPEN").sum()))
    print("Wins/Losses:", f"{wins}/{losses}")
    print("Win rate:", round(win_rate, 2), "%")

    print("\nCierres:")
    print(trades["close_reason"].value_counts(dropna=False).to_string())

    print("\nÚltimos 20:")
    cols = [
        "status",
        "crypto_symbol",
        "outcome",
        "entry_price",
        "exit_price",
        "pnl_usd",
        "pnl_pct",
        "entry_score",
        "entry_edge",
        "entry_decision",
        "close_reason",
        "question",
    ]
    cols = [c for c in cols if c in trades.columns]
    print(trades[cols].tail(20).to_string(index=False))


def main() -> None:
    now = now_utc()

    snapshot = load_snapshot()
    trades_old = load_trades()

    open_df, closed_df = split_status(trades_old)
    still_open, newly_closed = update_open_positions(open_df, snapshot, now)

    candidates = build_candidates(snapshot)

    last_entry = build_last_entry_map(trades_old)
    open_keys = {str(p.get("cooldown_key", "")) for p in still_open}

    opened = []

    for _, row in candidates.iterrows():
        if len(still_open) + len(opened) >= MAX_OPEN:
            break

        if len(opened) >= MAX_NEW_PER_CYCLE:
            break

        key = cooldown_key(row)

        if key in open_keys:
            continue

        old_ts = last_entry.get(key)
        if old_ts is not None:
            minutes = (pd.Timestamp(now) - old_ts).total_seconds() / 60
            if 0 <= minutes <= ENTRY_COOLDOWN_MINUTES:
                continue

        trade = make_trade(row, now)
        opened.append(trade)
        open_keys.add(key)
        last_entry[key] = pd.Timestamp(now)

    final = pd.concat(
        [
            closed_df,
            pd.DataFrame(newly_closed),
            pd.DataFrame(still_open),
            pd.DataFrame(opened),
        ],
        ignore_index=True,
    )

    save_trades(final)
    print_status(final, candidates, opened, newly_closed)


if __name__ == "__main__":
    main()
