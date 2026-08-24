from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import os
import uuid

import pandas as pd


SNAPSHOT_PATH = Path(os.getenv("LIMIT_HUNTER_SNAPSHOT_PATH", "data/directional_limit_hunter_snapshot.csv"))
MARK_PATH = Path(os.getenv("LIMIT_HUNTER_MARK_SNAPSHOT_PATH", "data/universe_discovery/latest_combined.csv"))

ORDERS_PATH = Path(os.getenv("LIMIT_HUNTER_ORDERS_PATH", "data/directional_limit_hunter_orders.csv"))
TRADES_PATH = Path(os.getenv("LIMIT_HUNTER_TRADES_PATH", "data/directional_limit_hunter_trades.csv"))

TRADE_USD = float(os.getenv("LIMIT_HUNTER_TRADE_USD", "0.25"))
MAX_OPEN = int(os.getenv("LIMIT_HUNTER_MAX_OPEN", "2"))
MAX_PENDING = int(os.getenv("LIMIT_HUNTER_MAX_PENDING", "5"))
MAX_NEW_ORDERS_PER_CYCLE = int(os.getenv("LIMIT_HUNTER_MAX_NEW_ORDERS_PER_CYCLE", "2"))

TAKE_PROFIT_PCT = float(os.getenv("LIMIT_HUNTER_TAKE_PROFIT_PCT", "4"))
STOP_LOSS_PCT = float(os.getenv("LIMIT_HUNTER_STOP_LOSS_PCT", "8"))
MAX_HOLD_MINUTES = float(os.getenv("LIMIT_HUNTER_MAX_HOLD_MINUTES", "180"))
PENDING_TTL_MINUTES = float(os.getenv("LIMIT_HUNTER_PENDING_TTL_MINUTES", "90"))
ENTRY_COOLDOWN_MINUTES = float(os.getenv("LIMIT_HUNTER_ENTRY_COOLDOWN_MINUTES", "60"))
CANCEL_WHEN_SIGNAL_GONE = os.getenv("LIMIT_HUNTER_CANCEL_WHEN_SIGNAL_GONE", "1") == "1"
SIGNAL_GONE_GRACE_CYCLES = int(os.getenv("LIMIT_HUNTER_SIGNAL_GONE_GRACE_CYCLES", "3"))


ORDER_COLUMNS = [
    "order_id",
    "status",
    "created_at",
    "filled_at",
    "canceled_at",
    "cancel_reason",
    "signal_miss_count",
    "match_key",
    "token_id",
    "question",
    "outcome",
    "crypto_symbol",
    "directional_side",
    "limit_price",
    "created_best_bid",
    "created_best_ask",
    "current_best_bid",
    "current_best_ask",
    "score",
    "fair_probability",
    "fair_edge_to_ask",
    "limit_edge",
    "crypto_decision",
    "crypto_alignment",
    "binance_bias",
]

TRADE_COLUMNS = [
    "trade_id",
    "order_id",
    "status",
    "entry_time",
    "exit_time",
    "match_key",
    "token_id",
    "question",
    "outcome",
    "crypto_symbol",
    "directional_side",
    "entry_price",
    "current_bid",
    "current_ask",
    "exit_price",
    "trade_usd",
    "shares",
    "pnl_usd",
    "pnl_pct",
    "entry_score",
    "entry_edge",
    "entry_limit_edge",
    "entry_decision",
    "entry_alignment",
    "entry_binance_bias",
    "close_reason",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_dt(value):
    return pd.to_datetime(value, utc=True, errors="coerce")


def minutes_since(value: str, now_ts) -> float:
    ts = to_dt(value)
    if pd.isna(ts):
        return 0.0
    return max(0.0, (now_ts - ts).total_seconds() / 60.0)


TEXT_COLUMNS = {
    "order_id",
    "trade_id",
    "status",
    "created_at",
    "filled_at",
    "canceled_at",
    "cancel_reason",
    "entry_time",
    "exit_time",
    "match_key",
    "token_id",
    "question",
    "outcome",
    "crypto_symbol",
    "directional_side",
    "crypto_decision",
    "crypto_alignment",
    "binance_bias",
    "entry_decision",
    "entry_alignment",
    "entry_binance_bias",
    "close_reason",
}


def read_table(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        df = pd.DataFrame(columns=columns)
    else:
        df = pd.read_csv(path)

    for col in columns:
        if col not in df.columns:
            df[col] = ""

    out = df[columns].copy()

    for col in columns:
        if col in TEXT_COLUMNS:
            out[col] = out[col].astype("object")
            out[col] = out[col].where(out[col].notna(), "")

    return out


def write_table(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def ensure_num(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        df[col] = pd.NA
    df[col] = pd.to_numeric(df[col], errors="coerce")


def ensure_text(df: pd.DataFrame, col: str) -> None:
    if col not in df.columns:
        df[col] = ""
    df[col] = df[col].astype(str)


def normalize_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    for col in [
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_probability",
        "fair_edge_to_ask",
        "limit_price",
        "limit_edge",
    ]:
        ensure_num(df, col)

    for col in [
        "token_id",
        "question",
        "outcome",
        "crypto_symbol",
        "directional_side",
        "crypto_decision",
        "crypto_alignment",
        "binance_bias",
    ]:
        ensure_text(df, col)

    if df["spread"].isna().all() and "best_bid" in df.columns and "best_ask" in df.columns:
        df["spread"] = df["best_ask"] - df["best_bid"]

    df["match_key"] = df.apply(make_key, axis=1)
    return df


def make_key(row: pd.Series) -> str:
    token_id = str(row.get("token_id", "")).strip()

    if token_id and token_id.lower() not in {"nan", "none", "<na>"}:
        return f"token:{token_id}"

    question = str(row.get("question", "")).strip()
    outcome = str(row.get("outcome", "")).strip().lower()
    symbol = str(row.get("crypto_symbol", "")).strip().upper()

    return f"q:{question}|o:{outcome}|s:{symbol}"


def mark_map(mark: pd.DataFrame) -> dict[str, pd.Series]:
    if mark.empty:
        return {}

    mark = normalize_snapshot(mark)
    mark = mark.drop_duplicates(subset=["match_key"], keep="first")
    return {str(row["match_key"]): row for _, row in mark.iterrows()}


def update_open_trades(trades: pd.DataFrame, marks: dict[str, pd.Series], now_ts) -> tuple[pd.DataFrame, int]:
    closed_count = 0

    if trades.empty:
        return trades, closed_count

    for idx, trade in trades[trades["status"].eq("OPEN")].iterrows():
        key = str(trade["match_key"])
        mark = marks.get(key)

        if mark is None:
            continue

        bid = pd.to_numeric(mark.get("best_bid"), errors="coerce")
        ask = pd.to_numeric(mark.get("best_ask"), errors="coerce")

        if pd.isna(bid):
            continue

        entry = pd.to_numeric(trade.get("entry_price"), errors="coerce")
        trade_usd = pd.to_numeric(trade.get("trade_usd"), errors="coerce")

        if pd.isna(entry) or entry <= 0:
            continue

        if pd.isna(trade_usd) or trade_usd <= 0:
            trade_usd = TRADE_USD

        shares = trade_usd / entry
        pnl_usd = shares * (bid - entry)
        pnl_pct = ((bid - entry) / entry) * 100.0

        trades.at[idx, "current_bid"] = bid
        trades.at[idx, "current_ask"] = ask
        trades.at[idx, "pnl_usd"] = pnl_usd
        trades.at[idx, "pnl_pct"] = pnl_pct
        trades.at[idx, "shares"] = shares

        age_min = minutes_since(str(trade.get("entry_time", "")), now_ts)

        close_reason = ""

        if pnl_pct >= TAKE_PROFIT_PCT:
            close_reason = "LIMIT_TAKE_PROFIT"
        elif pnl_pct <= -STOP_LOSS_PCT:
            close_reason = "LIMIT_STOP_LOSS"
        elif age_min >= MAX_HOLD_MINUTES:
            close_reason = "LIMIT_TIME_EXIT"

        if close_reason:
            trades.at[idx, "status"] = "CLOSED"
            trades.at[idx, "exit_time"] = now_iso()
            trades.at[idx, "exit_price"] = bid
            trades.at[idx, "close_reason"] = close_reason
            closed_count += 1

    return trades, closed_count


def update_pending_orders(
    orders: pd.DataFrame,
    trades: pd.DataFrame,
    marks: dict[str, pd.Series],
    now_ts,
    current_candidate_keys: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    filled_count = 0
    canceled_count = 0
    new_trades = []

    if orders.empty:
        return orders, trades, filled_count, canceled_count

    for idx, order in orders[orders["status"].eq("PENDING")].iterrows():
        key = str(order.get("match_key", ""))

        if current_candidate_keys is not None:
            raw_miss_count = pd.to_numeric(
                order.get("signal_miss_count", 0),
                errors="coerce",
            )

            if pd.isna(raw_miss_count):
                raw_miss_count = 0

            miss_count = int(raw_miss_count)

            if key not in current_candidate_keys:
                miss_count += 1
                orders.at[idx, "signal_miss_count"] = miss_count

                if CANCEL_WHEN_SIGNAL_GONE and miss_count >= SIGNAL_GONE_GRACE_CYCLES:
                    orders.at[idx, "status"] = "CANCELED"
                    orders.at[idx, "canceled_at"] = now_iso()
                    orders.at[idx, "cancel_reason"] = f"CURRENT_SIGNAL_GONE_{miss_count}_CYCLES"
                    canceled_count += 1
                    continue
            else:
                orders.at[idx, "signal_miss_count"] = 0

        age_min = minutes_since(str(order.get("created_at", "")), now_ts)

        if age_min >= PENDING_TTL_MINUTES:
            orders.at[idx, "status"] = "CANCELED"
            orders.at[idx, "canceled_at"] = now_iso()
            orders.at[idx, "cancel_reason"] = "PENDING_TTL_EXPIRED"
            canceled_count += 1
            continue

        key = str(order["match_key"])
        mark = marks.get(key)

        if mark is None:
            continue

        bid = pd.to_numeric(mark.get("best_bid"), errors="coerce")
        ask = pd.to_numeric(mark.get("best_ask"), errors="coerce")
        limit_price = pd.to_numeric(order.get("limit_price"), errors="coerce")

        orders.at[idx, "current_best_bid"] = bid
        orders.at[idx, "current_best_ask"] = ask

        if pd.isna(ask) or pd.isna(limit_price):
            continue

        if ask <= limit_price:
            order_id = str(order["order_id"])
            trade_id = f"lhtrade_{uuid.uuid4().hex[:12]}"
            shares = TRADE_USD / limit_price

            orders.at[idx, "status"] = "FILLED"
            orders.at[idx, "filled_at"] = now_iso()

            new_trades.append(
                {
                    "trade_id": trade_id,
                    "order_id": order_id,
                    "status": "OPEN",
                    "entry_time": now_iso(),
                    "exit_time": "",
                    "match_key": key,
                    "token_id": order.get("token_id", ""),
                    "question": order.get("question", ""),
                    "outcome": order.get("outcome", ""),
                    "crypto_symbol": order.get("crypto_symbol", ""),
                    "directional_side": order.get("directional_side", ""),
                    "entry_price": limit_price,
                    "current_bid": bid,
                    "current_ask": ask,
                    "exit_price": pd.NA,
                    "trade_usd": TRADE_USD,
                    "shares": shares,
                    "pnl_usd": 0.0,
                    "pnl_pct": 0.0,
                    "entry_score": order.get("score", pd.NA),
                    "entry_edge": order.get("fair_edge_to_ask", pd.NA),
                    "entry_limit_edge": order.get("limit_edge", pd.NA),
                    "entry_decision": order.get("crypto_decision", ""),
                    "entry_alignment": order.get("crypto_alignment", ""),
                    "entry_binance_bias": order.get("binance_bias", ""),
                    "close_reason": "",
                }
            )

            filled_count += 1

    if new_trades:
        trades = pd.concat([trades, pd.DataFrame(new_trades)], ignore_index=True)

    return orders, trades, filled_count, canceled_count


def active_keys(orders: pd.DataFrame, trades: pd.DataFrame) -> set[str]:
    keys: set[str] = set()

    if not orders.empty:
        pending = orders[orders["status"].eq("PENDING")]
        keys.update(pending["match_key"].dropna().astype(str).tolist())

    if not trades.empty:
        open_trades = trades[trades["status"].eq("OPEN")]
        keys.update(open_trades["match_key"].dropna().astype(str).tolist())

    return keys


def cooldown_keys(orders: pd.DataFrame, trades: pd.DataFrame, now_ts) -> set[str]:
    keys: set[str] = set()

    if not orders.empty:
        for _, row in orders.iterrows():
            created_at = str(row.get("created_at", ""))
            if minutes_since(created_at, now_ts) < ENTRY_COOLDOWN_MINUTES:
                keys.add(str(row.get("match_key", "")))

    if not trades.empty:
        for _, row in trades.iterrows():
            entry_time = str(row.get("entry_time", ""))
            if minutes_since(entry_time, now_ts) < ENTRY_COOLDOWN_MINUTES:
                keys.add(str(row.get("match_key", "")))

    return keys


def create_new_orders(
    candidates: pd.DataFrame,
    orders: pd.DataFrame,
    trades: pd.DataFrame,
    now_ts,
) -> tuple[pd.DataFrame, int]:
    new_count = 0

    if candidates.empty:
        return orders, new_count

    pending_count = int((orders["status"] == "PENDING").sum()) if not orders.empty else 0
    open_count = int((trades["status"] == "OPEN").sum()) if not trades.empty else 0

    if open_count >= MAX_OPEN or pending_count >= MAX_PENDING:
        return orders, new_count

    blocked = active_keys(orders, trades) | cooldown_keys(orders, trades, now_ts)

    new_rows = []

    for _, row in candidates.iterrows():
        if new_count >= MAX_NEW_ORDERS_PER_CYCLE:
            break

        pending_count = int((orders["status"] == "PENDING").sum()) + len(new_rows)

        if pending_count >= MAX_PENDING:
            break

        key = str(row["match_key"])

        if key in blocked:
            continue

        limit_price = pd.to_numeric(row.get("limit_price"), errors="coerce")

        if pd.isna(limit_price) or limit_price <= 0:
            continue

        order_id = f"lhorder_{uuid.uuid4().hex[:12]}"

        new_rows.append(
            {
                "order_id": order_id,
                "status": "PENDING",
                "created_at": now_iso(),
                "filled_at": "",
                "canceled_at": "",
                "cancel_reason": "",
                "signal_miss_count": 0,
                "match_key": key,
                "token_id": row.get("token_id", ""),
                "question": row.get("question", ""),
                "outcome": row.get("outcome", ""),
                "crypto_symbol": row.get("crypto_symbol", ""),
                "directional_side": row.get("directional_side", ""),
                "limit_price": limit_price,
                "created_best_bid": row.get("best_bid", pd.NA),
                "created_best_ask": row.get("best_ask", pd.NA),
                "current_best_bid": row.get("best_bid", pd.NA),
                "current_best_ask": row.get("best_ask", pd.NA),
                "score": row.get("score", pd.NA),
                "fair_probability": row.get("fair_probability", pd.NA),
                "fair_edge_to_ask": row.get("fair_edge_to_ask", pd.NA),
                "limit_edge": row.get("limit_edge", pd.NA),
                "crypto_decision": row.get("crypto_decision", ""),
                "crypto_alignment": row.get("crypto_alignment", ""),
                "binance_bias": row.get("binance_bias", ""),
            }
        )

        blocked.add(key)
        new_count += 1

    if new_rows:
        orders = pd.concat([orders, pd.DataFrame(new_rows)], ignore_index=True)

    return orders, new_count


def main() -> None:
    now_ts = pd.Timestamp.now(tz="UTC")

    if not SNAPSHOT_PATH.exists():
        print(f"No existe snapshot de candidatos: {SNAPSHOT_PATH}")
        return

    candidates = pd.read_csv(SNAPSHOT_PATH)
    candidates = normalize_snapshot(candidates)

    if MARK_PATH.exists():
        mark = pd.read_csv(MARK_PATH)
    else:
        mark = pd.DataFrame()

    marks = mark_map(mark)

    orders = read_table(ORDERS_PATH, ORDER_COLUMNS)
    trades = read_table(TRADES_PATH, TRADE_COLUMNS)

    orders_before = len(orders)
    trades_before = len(trades)

    current_candidate_keys = set(candidates["match_key"].dropna().astype(str).tolist())

    trades, closed_count = update_open_trades(trades, marks, now_ts)
    orders, trades, filled_count, canceled_count = update_pending_orders(
        orders,
        trades,
        marks,
        now_ts,
        current_candidate_keys,
    )
    orders, new_orders_count = create_new_orders(candidates, orders, trades, now_ts)

    write_table(ORDERS_PATH, orders)
    write_table(TRADES_PATH, trades)

    pending = int((orders["status"] == "PENDING").sum()) if not orders.empty else 0
    filled = int((orders["status"] == "FILLED").sum()) if not orders.empty else 0
    canceled = int((orders["status"] == "CANCELED").sum()) if not orders.empty else 0

    open_trades = int((trades["status"] == "OPEN").sum()) if not trades.empty else 0
    closed_trades = int((trades["status"] == "CLOSED").sum()) if not trades.empty else 0
    pnl_total = float(pd.to_numeric(trades["pnl_usd"], errors="coerce").fillna(0).sum()) if not trades.empty else 0.0

    print("\n=== DIRECTIONAL LIMIT HUNTER EXECUTION ===")
    print("Candidates snapshot:", SNAPSHOT_PATH)
    print("Mark snapshot:", MARK_PATH)
    print("Orders file:", ORDERS_PATH)
    print("Trades file:", TRADES_PATH)
    print(f"Trade USD: ${TRADE_USD}")
    print(f"Max open: {MAX_OPEN}")
    print(f"Max pending: {MAX_PENDING}")
    print(f"Max new orders/cycle: {MAX_NEW_ORDERS_PER_CYCLE}")
    print(f"TP/SL: +{TAKE_PROFIT_PCT:.2f}% / -{STOP_LOSS_PCT:.2f}%")
    print(f"Max hold: {MAX_HOLD_MINUTES:.1f} min")
    print(f"Pending TTL: {PENDING_TTL_MINUTES:.1f} min")
    print(f"Cooldown: {ENTRY_COOLDOWN_MINUTES:.1f} min")
    print(f"Cancel when signal gone: {CANCEL_WHEN_SIGNAL_GONE}")
    print(f"Signal gone grace cycles: {SIGNAL_GONE_GRACE_CYCLES}")

    print("\nCandidatos disponibles:", len(candidates))
    print("Órdenes antes/después:", f"{orders_before}/{len(orders)}")
    print("Trades antes/después:", f"{trades_before}/{len(trades)}")
    print("Nuevas órdenes:", new_orders_count)
    print("Filled este ciclo:", filled_count)
    print("Canceladas este ciclo:", canceled_count)
    print("Cerrados este ciclo:", closed_count)

    print("\nStatus órdenes:")
    if len(orders):
        print(orders["status"].value_counts(dropna=False).to_string())
    else:
        print("Sin órdenes todavía.")

    print("\nStatus trades:")
    if len(trades):
        print(trades["status"].value_counts(dropna=False).to_string())
    else:
        print("Sin trades todavía.")

    print("\nPnL total:", round(pnl_total, 6))

    if len(orders):
        print("\nÚltimas órdenes:")
        cols = [
            "status",
            "crypto_symbol",
            "outcome",
            "limit_price",
            "created_best_bid",
            "created_best_ask",
            "current_best_bid",
            "current_best_ask",
            "score",
            "limit_edge",
            "signal_miss_count",
            "crypto_decision",
            "question",
        ]
        cols = [c for c in cols if c in orders.columns]
        print(orders[cols].tail(10).to_string(index=False))

    if len(trades):
        print("\nÚltimos trades:")
        cols = [
            "status",
            "crypto_symbol",
            "outcome",
            "entry_price",
            "current_bid",
            "current_ask",
            "exit_price",
            "pnl_usd",
            "pnl_pct",
            "entry_score",
            "entry_limit_edge",
            "close_reason",
            "question",
        ]
        cols = [c for c in cols if c in trades.columns]
        print(trades[cols].tail(10).to_string(index=False))


if __name__ == "__main__":
    main()
