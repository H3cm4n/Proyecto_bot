from __future__ import annotations

from pathlib import Path
import os
import uuid

import pandas as pd


JOURNAL_PATH = Path(os.getenv("CANDIDATE_JOURNAL_PATH", "data/candidate_journal.csv"))
TRADES_PATH = Path(os.getenv("MICRO_TPSL_TRADES_PATH", "data/micro_tpsl_paper_trades.csv"))

ENABLED = os.getenv("MICRO_TPSL_ENABLED", "0").strip().lower() in {"1", "true", "yes", "y"}

TRADE_USD = float(os.getenv("MICRO_TPSL_TRADE_USD", "2"))
MAX_OPEN = int(os.getenv("MICRO_TPSL_MAX_OPEN", "1"))
MAX_NEW_PER_CYCLE = int(os.getenv("MICRO_TPSL_MAX_NEW_TRADES_PER_CYCLE", "1"))

TAKE_PROFIT_PCT = float(os.getenv("MICRO_TPSL_TAKE_PROFIT_PCT", "4"))
STOP_LOSS_PCT = float(os.getenv("MICRO_TPSL_STOP_LOSS_PCT", "8"))
MAX_HOLD_MINUTES = float(os.getenv("MICRO_TPSL_MAX_HOLD_MINUTES", "180"))

ENTRY_COOLDOWN_MINUTES = float(os.getenv("MICRO_TPSL_ENTRY_COOLDOWN_MINUTES", "180"))
CONFIRMATION_WINDOW_MINUTES = float(os.getenv("MICRO_TPSL_CONFIRMATION_WINDOW_MINUTES", "10"))
MIN_CONFIRMATIONS = int(os.getenv("MICRO_TPSL_MIN_CONFIRMATIONS", "1"))

MIN_EDGE = float(os.getenv("MICRO_TPSL_MIN_EDGE", "0.30"))
MIN_SCORE = float(os.getenv("MICRO_TPSL_MIN_SCORE", "80"))
MAX_SPREAD = float(os.getenv("MICRO_TPSL_MAX_SPREAD", "0.01"))
MIN_ASK = float(os.getenv("MICRO_TPSL_MIN_ASK", "0.50"))
MAX_ASK = float(os.getenv("MICRO_TPSL_MAX_ASK", "0.60"))

MAX_ENTRY_AGE_MINUTES = float(os.getenv("MICRO_TPSL_MAX_ENTRY_AGE_MINUTES", "15"))
MAX_MARK_AGE_MINUTES = float(os.getenv("MICRO_TPSL_MAX_MARK_AGE_MINUTES", "30"))

ALLOWED_SYMBOLS = {
    x.strip().upper()
    for x in os.getenv("MICRO_TPSL_ALLOWED_SYMBOLS", "BTCUSDT").split(",")
    if x.strip()
}

ALLOWED_OUTCOMES = {
    x.strip().lower()
    for x in os.getenv("MICRO_TPSL_ALLOWED_OUTCOMES", "Yes").split(",")
    if x.strip()
}

ALLOWED_DECISIONS = {
    x.strip()
    for x in os.getenv("MICRO_TPSL_ALLOWED_DECISIONS", "CRYPTO_BUY_FAIR_EDGE").split(",")
    if x.strip()
}

ALLOWED_ALIGNMENT = {
    x.strip().upper()
    for x in os.getenv("MICRO_TPSL_ALLOWED_ALIGNMENT", "ALIGNED").split(",")
    if x.strip()
}

ALLOWED_FLOW = {
    x.strip().upper()
    for x in os.getenv("MICRO_TPSL_ALLOWED_FLOW", "BULLISH").split(",")
    if x.strip()
}


TRADE_COLUMNS = [
    "trade_id",
    "status",
    "strategy",
    "signal_key",
    "token_id",
    "question",
    "crypto_symbol",
    "outcome",
    "entry_time",
    "exit_time",
    "last_checked_at",
    "entry_price",
    "entry_bid",
    "entry_ask",
    "current_bid",
    "current_ask",
    "exit_price",
    "trade_usd",
    "quantity",
    "current_value_usd",
    "pnl_usd",
    "pnl_pct",
    "take_profit_pct",
    "stop_loss_pct",
    "take_profit_price",
    "stop_loss_price",
    "max_hold_minutes",
    "close_reason",
    "entry_decision",
    "entry_score",
    "entry_edge",
    "entry_spread",
    "entry_flow_bias",
    "entry_alignment",
    "confirmation_count_10m",
    "latest_decision",
    "latest_flow_bias",
    "latest_alignment",
    "last_update_status",
]


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


def ensure_column(df: pd.DataFrame, column: str, default="") -> None:
    if column not in df.columns:
        df[column] = default


def load_journal() -> pd.DataFrame:
    if not JOURNAL_PATH.exists():
        return pd.DataFrame()

    df = pd.read_csv(JOURNAL_PATH)

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
        ensure_column(df, col, None)
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in [
        "token_id",
        "question",
        "crypto_symbol",
        "outcome",
        "crypto_decision",
        "crypto_alignment",
        "flow_bias",
    ]:
        ensure_column(df, col, "")

    df["crypto_symbol"] = df["crypto_symbol"].fillna("").astype(str).str.upper()
    df["outcome"] = df["outcome"].fillna("").astype(str)
    df["crypto_decision"] = df["crypto_decision"].fillna("").astype(str)
    df["crypto_alignment"] = df["crypto_alignment"].fillna("").astype(str).str.upper()
    df["flow_bias"] = df["flow_bias"].fillna("").astype(str).str.upper()
    df["signal_key"] = df.apply(signal_key, axis=1)

    return df.sort_values("observed_at").reset_index(drop=True)


def load_trades() -> pd.DataFrame:
    if not TRADES_PATH.exists():
        return pd.DataFrame(columns=TRADE_COLUMNS)

    df = pd.read_csv(TRADES_PATH)

    for col in TRADE_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # Pandas puede inferir columnas vacías como float64.
    # Eso rompe cuando luego queremos escribir timestamps/strings como exit_time.
    text_cols = [
        "trade_id",
        "status",
        "strategy",
        "signal_key",
        "token_id",
        "question",
        "crypto_symbol",
        "outcome",
        "entry_time",
        "exit_time",
        "last_checked_at",
        "close_reason",
        "entry_decision",
        "entry_flow_bias",
        "entry_alignment",
        "latest_decision",
        "latest_flow_bias",
        "latest_alignment",
        "last_update_status",
    ]

    for col in text_cols:
        if col in df.columns:
            df[col] = df[col].astype("object")

    return df[TRADE_COLUMNS].copy()


def save_trades(df: pd.DataFrame) -> None:
    TRADES_PATH.parent.mkdir(parents=True, exist_ok=True)

    for col in TRADE_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df[TRADE_COLUMNS].to_csv(TRADES_PATH, index=False)


def confirmation_count(row: pd.Series, journal: pd.DataFrame) -> int:
    start = row["observed_at"] - pd.Timedelta(minutes=CONFIRMATION_WINDOW_MINUTES)

    rows = journal[
        journal["signal_key"].eq(row["signal_key"])
        & (journal["observed_at"] >= start)
        & (journal["observed_at"] <= row["observed_at"])
        & journal["crypto_decision"].isin(ALLOWED_DECISIONS)
    ]

    return int(len(rows))


def latest_market_row(signal: str, journal: pd.DataFrame) -> pd.Series | None:
    rows = journal[journal["signal_key"].eq(signal)].copy()

    if rows.empty:
        return None

    return rows.iloc[-1]


def update_open_trades(trades: pd.DataFrame, journal: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return trades

    now = pd.Timestamp.now(tz="UTC")
    open_mask = trades["status"].fillna("").astype(str).str.upper().eq("OPEN")

    for idx in trades[open_mask].index:
        signal = safe_str(trades.loc[idx, "signal_key"])
        latest = latest_market_row(signal, journal)

        if latest is None:
            trades.loc[idx, "last_update_status"] = "NO_MARKET_ROW"
            continue

        mark_time = latest["observed_at"]
        mark_age_min = (now - mark_time).total_seconds() / 60

        if mark_age_min > MAX_MARK_AGE_MINUTES:
            trades.loc[idx, "last_update_status"] = f"STALE_MARK_{mark_age_min:.1f}_MIN"
            continue

        entry_price = safe_float(trades.loc[idx, "entry_price"])
        trade_usd = safe_float(trades.loc[idx, "trade_usd"], 0.0)
        quantity = safe_float(trades.loc[idx, "quantity"], 0.0)
        bid = safe_float(latest.get("best_bid"))
        ask = safe_float(latest.get("best_ask"))

        if entry_price is None or entry_price <= 0 or bid is None:
            trades.loc[idx, "last_update_status"] = "INVALID_MARK"
            continue

        current_value = quantity * bid
        pnl_usd = current_value - trade_usd
        pnl_pct = ((bid - entry_price) / entry_price) * 100

        trades.loc[idx, "current_bid"] = bid
        trades.loc[idx, "current_ask"] = ask
        trades.loc[idx, "current_value_usd"] = current_value
        trades.loc[idx, "pnl_usd"] = pnl_usd
        trades.loc[idx, "pnl_pct"] = pnl_pct
        trades.loc[idx, "latest_decision"] = latest.get("crypto_decision")
        trades.loc[idx, "latest_flow_bias"] = latest.get("flow_bias")
        trades.loc[idx, "latest_alignment"] = latest.get("crypto_alignment")
        trades.loc[idx, "last_checked_at"] = now.isoformat()
        trades.loc[idx, "last_update_status"] = "UPDATED"

        entry_time = pd.to_datetime(trades.loc[idx, "entry_time"], errors="coerce", utc=True)

        if pd.isna(entry_time):
            age_min = 0.0
        else:
            age_min = (mark_time - entry_time).total_seconds() / 60

        close_reason = None

        if pnl_pct >= TAKE_PROFIT_PCT:
            close_reason = "MICRO_TAKE_PROFIT"
        elif pnl_pct <= -STOP_LOSS_PCT:
            close_reason = "MICRO_STOP_LOSS"
        elif age_min >= MAX_HOLD_MINUTES:
            close_reason = "MICRO_TIME_EXIT"

        if close_reason:
            trades.loc[idx, "status"] = "CLOSED"
            trades.loc[idx, "exit_time"] = mark_time.isoformat()
            trades.loc[idx, "exit_price"] = bid
            trades.loc[idx, "close_reason"] = close_reason
            trades.loc[idx, "last_update_status"] = f"CLOSED_{close_reason}"

    return trades


def cooldown_blocked(candidate: pd.Series, trades: pd.DataFrame) -> bool:
    if trades.empty:
        return False

    same = trades[trades["signal_key"].fillna("").astype(str).eq(candidate["signal_key"])].copy()

    if same.empty:
        return False

    same["entry_time_dt"] = pd.to_datetime(same["entry_time"], errors="coerce", utc=True)
    same = same.dropna(subset=["entry_time_dt"])

    if same.empty:
        return False

    last_entry = same["entry_time_dt"].max()
    age_min = (candidate["observed_at"] - last_entry).total_seconds() / 60

    return age_min < ENTRY_COOLDOWN_MINUTES


def select_entry_candidates(journal: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    if journal.empty:
        return pd.DataFrame()

    latest_time = journal["observed_at"].max()
    now = pd.Timestamp.now(tz="UTC")
    latest_age_min = (now - latest_time).total_seconds() / 60

    if latest_age_min > MAX_ENTRY_AGE_MINUTES:
        print(f"Entrada bloqueada: último snapshot viejo ({latest_age_min:.1f} min).")
        return pd.DataFrame()

    current = journal[journal["observed_at"].eq(latest_time)].copy()

    if current.empty:
        return current

    current["confirmation_count_10m"] = current.apply(
        lambda row: confirmation_count(row, journal),
        axis=1,
    )

    candidates = current[
        current["crypto_symbol"].isin(ALLOWED_SYMBOLS)
        & current["outcome"].fillna("").astype(str).str.lower().isin(ALLOWED_OUTCOMES)
        & current["crypto_decision"].isin(ALLOWED_DECISIONS)
        & current["crypto_alignment"].isin(ALLOWED_ALIGNMENT)
        & current["flow_bias"].isin(ALLOWED_FLOW)
        & (current["fair_edge_to_ask"] >= MIN_EDGE)
        & (current["score"] >= MIN_SCORE)
        & (current["spread"] <= MAX_SPREAD + 1e-12)
        & (current["best_ask"] >= MIN_ASK)
        & (current["best_ask"] <= MAX_ASK)
        & (current["confirmation_count_10m"] >= MIN_CONFIRMATIONS)
    ].copy()

    if candidates.empty:
        return candidates

    blocked = []

    for _, row in candidates.iterrows():
        blocked.append(cooldown_blocked(row, trades))

    candidates["cooldown_blocked"] = blocked
    candidates = candidates[~candidates["cooldown_blocked"]].copy()

    if candidates.empty:
        return candidates

    candidates = candidates.sort_values(
        ["fair_edge_to_ask", "score", "spread", "best_ask"],
        ascending=[False, False, True, True],
    )

    candidates = candidates.drop_duplicates(subset=["signal_key"], keep="first")

    return candidates


def open_new_trades(trades: pd.DataFrame, journal: pd.DataFrame) -> pd.DataFrame:
    if not ENABLED:
        return trades

    open_count = int(trades["status"].fillna("").astype(str).str.upper().eq("OPEN").sum())

    if open_count >= MAX_OPEN:
        print(f"No se abren entradas: max open alcanzado ({open_count}/{MAX_OPEN}).")
        return trades

    slots = max(0, MAX_OPEN - open_count)
    max_new = min(MAX_NEW_PER_CYCLE, slots)

    if max_new <= 0:
        return trades

    candidates = select_entry_candidates(journal, trades)

    if candidates.empty:
        print("Micro TPSL: no hay candidatos que pasen filtros.")
        return trades

    new_rows = []

    for _, row in candidates.head(max_new).iterrows():
        entry_ask = safe_float(row.get("best_ask"))
        entry_bid = safe_float(row.get("best_bid"))

        if entry_ask is None or entry_ask <= 0:
            continue

        quantity = TRADE_USD / entry_ask
        current_value = quantity * (entry_bid if entry_bid is not None else entry_ask)
        pnl_usd = current_value - TRADE_USD
        pnl_pct = ((entry_bid - entry_ask) / entry_ask) * 100 if entry_bid is not None else 0.0

        trade_id = f"micro_{row['observed_at'].strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"

        new_rows.append(
            {
                "trade_id": trade_id,
                "status": "OPEN",
                "strategy": "MICRO_TPSL_BTC_ALIGNED_BULLISH",
                "signal_key": row.get("signal_key"),
                "token_id": row.get("token_id"),
                "question": row.get("question"),
                "crypto_symbol": row.get("crypto_symbol"),
                "outcome": row.get("outcome"),
                "entry_time": row["observed_at"].isoformat(),
                "exit_time": None,
                "last_checked_at": pd.Timestamp.now(tz="UTC").isoformat(),
                "entry_price": entry_ask,
                "entry_bid": entry_bid,
                "entry_ask": entry_ask,
                "current_bid": entry_bid,
                "current_ask": row.get("best_ask"),
                "exit_price": None,
                "trade_usd": TRADE_USD,
                "quantity": quantity,
                "current_value_usd": current_value,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "take_profit_pct": TAKE_PROFIT_PCT,
                "stop_loss_pct": STOP_LOSS_PCT,
                "take_profit_price": entry_ask * (1 + TAKE_PROFIT_PCT / 100),
                "stop_loss_price": entry_ask * (1 - STOP_LOSS_PCT / 100),
                "max_hold_minutes": MAX_HOLD_MINUTES,
                "close_reason": None,
                "entry_decision": row.get("crypto_decision"),
                "entry_score": row.get("score"),
                "entry_edge": row.get("fair_edge_to_ask"),
                "entry_spread": row.get("spread"),
                "entry_flow_bias": row.get("flow_bias"),
                "entry_alignment": row.get("crypto_alignment"),
                "confirmation_count_10m": row.get("confirmation_count_10m"),
                "latest_decision": row.get("crypto_decision"),
                "latest_flow_bias": row.get("flow_bias"),
                "latest_alignment": row.get("crypto_alignment"),
                "last_update_status": "OPENED",
            }
        )

    if new_rows:
        trades = pd.concat([trades, pd.DataFrame(new_rows)], ignore_index=True)

    return trades


def print_report(trades: pd.DataFrame) -> None:
    print("\n=== MICRO TPSL PAPER EXECUTION ===")
    print("Strategy: MICRO_TPSL_BTC_ALIGNED_BULLISH")
    print(f"Enabled: {ENABLED}")
    print(f"Archivo: {TRADES_PATH}")
    print(f"Trade USD: ${TRADE_USD:.2f}")
    print(f"Max open: {MAX_OPEN}")
    print(f"Max new/cycle: {MAX_NEW_PER_CYCLE}")
    print(f"TP/SL: +{TAKE_PROFIT_PCT:.2f}% / -{STOP_LOSS_PCT:.2f}%")
    print(f"Max hold: {MAX_HOLD_MINUTES:.1f} min")
    print(f"Cooldown: {ENTRY_COOLDOWN_MINUTES:.1f} min")
    print(f"Filtros: symbols={sorted(ALLOWED_SYMBOLS)} outcomes={sorted(ALLOWED_OUTCOMES)} flow={sorted(ALLOWED_FLOW)}")
    print(f"Edge >= {MIN_EDGE}, score >= {MIN_SCORE}, spread <= {MAX_SPREAD}, ask {MIN_ASK}-{MAX_ASK}, confirmations >= {MIN_CONFIRMATIONS}")

    if trades.empty:
        print("Sin trades micro.")
        return

    status_counts = trades["status"].fillna("").value_counts()
    print("\nStatus:")
    print(status_counts.to_string())

    closed = trades[trades["status"].fillna("").astype(str).str.upper().eq("CLOSED")].copy()
    open_trades = trades[trades["status"].fillna("").astype(str).str.upper().eq("OPEN")].copy()

    total_pnl = pd.to_numeric(trades["pnl_usd"], errors="coerce").fillna(0).sum()
    closed_pnl = pd.to_numeric(closed["pnl_usd"], errors="coerce").fillna(0).sum() if not closed.empty else 0.0
    open_pnl = pd.to_numeric(open_trades["pnl_usd"], errors="coerce").fillna(0).sum() if not open_trades.empty else 0.0

    print(f"\nPnL total marcado: ${total_pnl:.4f}")
    print(f"PnL cerrado: ${closed_pnl:.4f}")
    print(f"PnL abierto: ${open_pnl:.4f}")

    if not closed.empty:
        pnl_pct = pd.to_numeric(closed["pnl_pct"], errors="coerce")
        wins = int((pnl_pct > 0).sum())
        losses = int((pnl_pct < 0).sum())
        flats = int((pnl_pct == 0).sum())
        win_rate = wins / len(closed) * 100 if len(closed) else 0.0

        print(f"Win rate cerrado: {win_rate:.2f}%")
        print(f"Wins/Losses/Flat: {wins}/{losses}/{flats}")

        print("\nCierres por razón:")
        print(closed["close_reason"].fillna("").value_counts().to_string())

    cols = [
        "status",
        "crypto_symbol",
        "outcome",
        "entry_price",
        "current_bid",
        "current_ask",
        "trade_usd",
        "pnl_usd",
        "pnl_pct",
        "entry_edge",
        "entry_score",
        "entry_flow_bias",
        "latest_flow_bias",
        "close_reason",
        "question",
    ]

    print("\nÚltimos micro trades:")
    print(trades[cols].tail(10).to_string(index=False))


def main() -> None:
    journal = load_journal()
    trades = load_trades()

    if journal.empty:
        print("\n=== MICRO TPSL PAPER EXECUTION ===")
        print(f"Enabled: {ENABLED}")
        print(f"No existe o está vacío: {JOURNAL_PATH}")
        save_trades(trades)
        return

    trades = update_open_trades(trades, journal)
    trades = open_new_trades(trades, journal)
    save_trades(trades)
    print_report(trades)


if __name__ == "__main__":
    main()
