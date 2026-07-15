from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.signals.research_lanes import classify_research_lane, flow_support_label, safe_str


SNAPSHOT_PATH = Path("data/crypto_signal_snapshot_fair_value.csv")
FLOW_PATH = Path("data/binance_flow_snapshot.csv")
OUT = Path(os.getenv("RESEARCH_PAPER_TRADES_PATH", "data/research_paper_trades.csv"))


TEXT_COLUMNS = [
    "opened_at",
    "last_seen_at",
    "closed_at",
    "status",
    "strategy",
    "signal_key",
    "question",
    "outcome",
    "crypto_symbol",
    "crypto_decision",
    "crypto_alignment",
    "binance_bias",
    "flow_bias",
    "flow_support",
    "trade_direction",
    "research_reason",
    "close_reason",
]

ALL_COLUMNS = TEXT_COLUMNS + [
    "entry_price",
    "current_bid",
    "current_ask",
    "trade_usd",
    "shares",
    "current_value_usd",
    "pnl_usd",
    "pnl_pct",
    "take_profit_price",
    "stop_loss_price",
    "score",
    "fair_edge_to_ask",
    "spread",
    "not_seen_count",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def as_float(value, default=None):
    try:
        if value is None:
            return default

        text = str(value).strip()

        if text == "" or text.lower() == "nan":
            return default

        return float(text)
    except Exception:
        return default


def signal_key(row) -> str:
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


def load_flow() -> dict[str, dict]:
    if not FLOW_PATH.exists():
        return {}

    try:
        df = pd.read_csv(FLOW_PATH)
    except Exception:
        return {}

    if df.empty or "symbol" not in df.columns:
        return {}

    rows = {}

    for _, row in df.iterrows():
        symbol = safe_str(row.get("symbol")).strip().upper()

        if symbol:
            rows[symbol] = row.to_dict()

    return rows


def load_trades() -> pd.DataFrame:
    if not OUT.exists():
        return pd.DataFrame(columns=ALL_COLUMNS)

    try:
        df = pd.read_csv(OUT)
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=ALL_COLUMNS)

    for col in ALL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    for col in TEXT_COLUMNS:
        df[col] = df[col].fillna("").astype("object")

    numeric_cols = [col for col in ALL_COLUMNS if col not in TEXT_COLUMNS]

    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["not_seen_count"] = df["not_seen_count"].fillna(0).astype(int)

    return df


def save_trades(df: pd.DataFrame) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)


def cooldown_active(trades: pd.DataFrame, key: str, cooldown_minutes: int) -> bool:
    if trades.empty or cooldown_minutes <= 0:
        return False

    closed = trades[
        trades["signal_key"].astype(str).eq(str(key))
        & trades["status"].astype(str).eq("CLOSED")
    ].copy()

    if closed.empty or "closed_at" not in closed.columns:
        return False

    closed["closed_at_dt"] = pd.to_datetime(closed["closed_at"], errors="coerce", utc=True)
    closed = closed.dropna(subset=["closed_at_dt"])

    if closed.empty:
        return False

    latest_close = closed["closed_at_dt"].max()
    age_minutes = (datetime.now(timezone.utc) - latest_close.to_pydatetime()).total_seconds() / 60

    return age_minutes < cooldown_minutes


def main() -> None:
    enabled = os.getenv("RESEARCH_PAPER_ENABLED", "1") == "1"

    trade_usd = float(os.getenv("RESEARCH_TRADE_USD", "2"))
    max_open_trades = int(os.getenv("RESEARCH_MAX_OPEN_TRADES", "1"))
    max_exposure_usd = float(os.getenv("RESEARCH_MAX_EXPOSURE_USD", "4"))
    max_new_trades = int(os.getenv("RESEARCH_MAX_NEW_TRADES_PER_CYCLE", "1"))

    ask_min = float(os.getenv("RESEARCH_EXEC_ASK_MIN", "0.06"))
    ask_max = float(os.getenv("RESEARCH_EXEC_ASK_MAX", "0.08"))
    spread_max = float(os.getenv("RESEARCH_EXEC_SPREAD_MAX", "0.001"))
    score_min = float(os.getenv("RESEARCH_EXEC_SCORE_MIN", "60"))
    take_profit = float(os.getenv("RESEARCH_TAKE_PROFIT", "0.02"))
    stop_loss = float(os.getenv("RESEARCH_STOP_LOSS", "0.02"))
    cooldown_minutes = int(os.getenv("RESEARCH_REENTRY_COOLDOWN_MINUTES", "30"))
    require_flow_support = os.getenv("RESEARCH_REQUIRE_FLOW_SUPPORT", "0") == "1"

    snapshot_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SNAPSHOT_PATH

    trades = load_trades()

    print("\n=== RESEARCH PAPER EXECUTION ===")
    print("Strategy: BTC_CHEAP_CONVEX")
    print(f"Enabled: {enabled}")

    if not enabled:
        save_trades(trades)
        print(f"Archivo: {OUT}")
        return

    if not snapshot_path.exists():
        print(f"No existe snapshot: {snapshot_path}")
        save_trades(trades)
        return

    try:
        snapshot = pd.read_csv(snapshot_path)
    except pd.errors.EmptyDataError:
        print("Snapshot vacío.")
        save_trades(trades)
        return

    if snapshot.empty:
        print("No hay filas en snapshot.")
        save_trades(trades)
        return

    snapshot = snapshot.copy()
    snapshot["_signal_key"] = snapshot.apply(signal_key, axis=1)

    latest_by_key = {
        key: group.iloc[-1]
        for key, group in snapshot.groupby("_signal_key", dropna=False)
    }

    flow_by_symbol = load_flow()
    now = now_iso()

    # 1) Actualizar posiciones abiertas.
    for idx, trade in trades[trades["status"].astype(str).eq("OPEN")].iterrows():
        key = safe_str(trade.get("signal_key"))

        latest = latest_by_key.get(key)

        if latest is None:
            trades.loc[idx, "not_seen_count"] = int(trades.loc[idx, "not_seen_count"] or 0) + 1
            continue

        bid = as_float(latest.get("best_bid"))
        ask = as_float(latest.get("best_ask"))
        entry = as_float(trade.get("entry_price"))
        shares = as_float(trade.get("shares"))
        trade_value = as_float(trade.get("trade_usd"), trade_usd)
        take_profit_price = as_float(trade.get("take_profit_price"))
        stop_loss_price = as_float(trade.get("stop_loss_price"))

        symbol = safe_str(trade.get("crypto_symbol")).strip().upper()
        flow_row = flow_by_symbol.get(symbol, {})
        flow_bias = safe_str(flow_row.get("flow_bias")).upper()
        trade_direction = safe_str(trade.get("trade_direction")).upper()
        flow_support = flow_support_label(flow_bias, trade_direction)

        trades.loc[idx, "last_seen_at"] = now
        trades.loc[idx, "current_bid"] = bid
        trades.loc[idx, "current_ask"] = ask
        trades.loc[idx, "flow_bias"] = flow_bias
        trades.loc[idx, "flow_support"] = flow_support
        trades.loc[idx, "not_seen_count"] = 0

        if bid is not None and entry is not None and shares is not None:
            current_value = shares * bid
            trades.loc[idx, "current_value_usd"] = current_value
            trades.loc[idx, "pnl_usd"] = current_value - trade_value
            trades.loc[idx, "pnl_pct"] = ((bid - entry) / entry) * 100

        if bid is not None and take_profit_price is not None and bid >= take_profit_price:
            trades.loc[idx, "status"] = "CLOSED"
            trades.loc[idx, "closed_at"] = now
            trades.loc[idx, "close_reason"] = "TAKE_PROFIT"

        elif bid is not None and stop_loss_price is not None and bid <= stop_loss_price:
            trades.loc[idx, "status"] = "CLOSED"
            trades.loc[idx, "closed_at"] = now
            trades.loc[idx, "close_reason"] = "STOP_LOSS"

    open_trades = trades[trades["status"].astype(str).eq("OPEN")]
    open_count = len(open_trades)
    open_exposure = pd.to_numeric(open_trades.get("trade_usd", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()

    existing_open_keys = set(open_trades["signal_key"].astype(str)) if not open_trades.empty else set()

    new_trades = []
    blocked = {
        "not_research": 0,
        "duplicate": 0,
        "cooldown": 0,
        "max_open": 0,
        "max_exposure": 0,
        "ask_range": 0,
        "spread": 0,
        "score": 0,
        "flow": 0,
    }

    # 2) Buscar nuevas entradas research.
    candidates = []

    for _, row in snapshot.iterrows():
        classified = classify_research_lane(row)

        if not classified["research_pass"]:
            blocked["not_research"] += 1
            continue

        key = signal_key(row)

        if key in existing_open_keys:
            blocked["duplicate"] += 1
            continue

        if cooldown_active(trades, key, cooldown_minutes):
            blocked["cooldown"] += 1
            continue

        ask = as_float(row.get("best_ask"))
        bid = as_float(row.get("best_bid"))
        spread = as_float(row.get("spread"))

        if spread is None and ask is not None and bid is not None:
            spread = ask - bid

        score = as_float(row.get("score"), 0.0)

        if ask is None or ask < ask_min or ask > ask_max:
            blocked["ask_range"] += 1
            continue

        if spread is None or spread > spread_max:
            blocked["spread"] += 1
            continue

        if score is None or score < score_min:
            blocked["score"] += 1
            continue

        symbol = safe_str(row.get("crypto_symbol")).strip().upper()
        flow_row = flow_by_symbol.get(symbol, {})
        flow_bias = safe_str(flow_row.get("flow_bias")).upper()
        trade_direction = classified["trade_direction"]
        flow_support = flow_support_label(flow_bias, trade_direction)

        if require_flow_support and flow_support != "SUPPORTS":
            blocked["flow"] += 1
            continue

        item = row.to_dict()
        item["_signal_key"] = key
        item["_research_reason"] = classified["research_reason"]
        item["_trade_direction"] = trade_direction
        item["_flow_bias"] = flow_bias
        item["_flow_support"] = flow_support
        item["_ask"] = ask
        item["_bid"] = bid
        item["_spread"] = spread
        item["_score"] = score
        candidates.append(item)

    candidates = sorted(
        candidates,
        key=lambda row: (
            -float(row.get("_score") or 0),
            float(row.get("_spread") or 999),
            float(row.get("_ask") or 999),
        ),
    )

    for row in candidates:
        if len(new_trades) >= max_new_trades:
            break

        if open_count + len(new_trades) >= max_open_trades:
            blocked["max_open"] += 1
            break

        if open_exposure + (len(new_trades) + 1) * trade_usd > max_exposure_usd:
            blocked["max_exposure"] += 1
            break

        ask = row["_ask"]
        bid = row["_bid"]
        shares = trade_usd / ask
        current_value = shares * bid if bid is not None else trade_usd
        pnl_usd = current_value - trade_usd
        pnl_pct = ((bid - ask) / ask) * 100 if bid is not None else 0.0

        new_trades.append(
            {
                "opened_at": now,
                "last_seen_at": now,
                "closed_at": "",
                "status": "OPEN",
                "strategy": "BTC_CHEAP_CONVEX",
                "signal_key": row["_signal_key"],
                "question": safe_str(row.get("question")),
                "outcome": safe_str(row.get("outcome")),
                "crypto_symbol": safe_str(row.get("crypto_symbol")).strip().upper(),
                "crypto_decision": safe_str(row.get("crypto_decision")),
                "crypto_alignment": safe_str(row.get("crypto_alignment")),
                "binance_bias": safe_str(row.get("binance_bias")),
                "flow_bias": row["_flow_bias"],
                "flow_support": row["_flow_support"],
                "trade_direction": row["_trade_direction"],
                "research_reason": row["_research_reason"],
                "close_reason": "",
                "entry_price": ask,
                "current_bid": bid,
                "current_ask": ask,
                "trade_usd": trade_usd,
                "shares": shares,
                "current_value_usd": current_value,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "take_profit_price": min(0.99, ask + take_profit),
                "stop_loss_price": max(0.01, ask - stop_loss),
                "score": row["_score"],
                "fair_edge_to_ask": as_float(row.get("fair_edge_to_ask")),
                "spread": row["_spread"],
                "not_seen_count": 0,
            }
        )

    if new_trades:
        trades = pd.concat([trades, pd.DataFrame(new_trades)], ignore_index=True)

    save_trades(trades)

    open_count = int((trades["status"].astype(str) == "OPEN").sum()) if not trades.empty else 0
    closed_count = int((trades["status"].astype(str) == "CLOSED").sum()) if not trades.empty else 0

    print(f"Nuevas entradas research: {len(new_trades)}")
    print(f"Posiciones abiertas research: {open_count}")
    print(f"Posiciones cerradas research: {closed_count}")
    print(f"Trade USD: ${trade_usd:.2f}")
    print(f"Ask permitido: {ask_min} - {ask_max}")
    print(f"Spread máximo: {spread_max}")
    print(f"Score mínimo: {score_min}")
    print(f"TP/SL contrato: +{take_profit} / -{stop_loss}")
    print(f"Cooldown: {cooldown_minutes} min")
    print(f"Require flow SUPPORTS: {require_flow_support}")
    print(f"Bloqueos: {blocked}")
    print(f"Archivo: {OUT}")

    if not trades.empty:
        cols = [
            "status",
            "strategy",
            "crypto_symbol",
            "outcome",
            "entry_price",
            "current_bid",
            "current_ask",
            "trade_usd",
            "pnl_usd",
            "pnl_pct",
            "close_reason",
            "question",
        ]
        cols = [col for col in cols if col in trades.columns]
        print(trades[cols].tail(10).to_string(index=False))


if __name__ == "__main__":
    main()
