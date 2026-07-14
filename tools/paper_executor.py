from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd


SNAPSHOT_PATH = "data/crypto_signal_snapshot_fair_value.csv"
TRADES_PATH = "data/paper_trades.csv"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_float(value):
    try:
        if pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def signal_key(row: pd.Series) -> str:
    token_id = str(row.get("token_id") or "").strip()
    if token_id and token_id.lower() != "nan":
        return token_id

    question = str(row.get("question") or "").strip()
    outcome = str(row.get("outcome") or "").strip()
    threshold = str(row.get("threshold_price") or "").strip()
    return f"{question}|{outcome}|{threshold}"


def load_trades(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def main() -> None:
    snapshot_path = Path(sys.argv[1] if len(sys.argv) > 1 else SNAPSHOT_PATH)
    trades_path = Path(os.getenv("PAPER_TRADES_PATH", TRADES_PATH))
    signal_journal_path = Path(os.getenv("SIGNAL_JOURNAL_PATH", "data/signal_journal.csv"))

    trade_usd = float(os.getenv("PAPER_TRADE_USD", "10"))
    take_profit = float(os.getenv("PAPER_TAKE_PROFIT", "0.15"))
    stop_loss = float(os.getenv("PAPER_STOP_LOSS", "0.08"))

    max_open_trades = int(os.getenv("PAPER_MAX_OPEN_TRADES", "3"))
    max_exposure_usd = float(os.getenv("PAPER_MAX_EXPOSURE_USD", "30"))
    max_new_trades_per_cycle = int(os.getenv("PAPER_MAX_NEW_TRADES_PER_CYCLE", "1"))
    close_on_binance_not_aligned = os.getenv("PAPER_CLOSE_ON_BINANCE_NOT_ALIGNED", "1") == "1"
    exit_confirmation_cycles = int(os.getenv("PAPER_EXIT_CONFIRMATION_CYCLES", "2"))
    reentry_cooldown_minutes = int(os.getenv("PAPER_REENTRY_COOLDOWN_MINUTES", "30"))
    require_signal_confirmation = os.getenv("PAPER_REQUIRE_SIGNAL_CONFIRMATION", "1") == "1"
    confirmation_min_observations = int(os.getenv("PAPER_CONFIRMATION_MIN_OBSERVATIONS", "2"))
    confirmation_lookback_minutes = int(os.getenv("PAPER_CONFIRMATION_LOOKBACK_MINUTES", "10"))

    max_entry_ask = float(os.getenv("PAPER_MAX_ENTRY_ASK", "0.60"))
    max_entry_spread = float(os.getenv("PAPER_MAX_ENTRY_SPREAD", "0.02"))
    min_entry_fair_edge = float(os.getenv("PAPER_MIN_ENTRY_FAIR_EDGE", "0.25"))
    min_entry_score = float(os.getenv("PAPER_MIN_ENTRY_SCORE", "80"))

    if not snapshot_path.exists():
        raise SystemExit(f"No existe snapshot: {snapshot_path}")

    snapshot = pd.read_csv(snapshot_path)

    if "crypto_decision" not in snapshot.columns:
        raise SystemExit("El snapshot no tiene crypto_decision.")

    trades_path.parent.mkdir(parents=True, exist_ok=True)
    trades = load_trades(trades_path)

    if signal_journal_path.exists():
        try:
            signal_journal = pd.read_csv(signal_journal_path)
        except pd.errors.EmptyDataError:
            signal_journal = pd.DataFrame()
    else:
        signal_journal = pd.DataFrame()

    # CSV safety: empty text columns like closed_at can be read as float64.
    # Force text-like columns to object so Pandas accepts ISO timestamps.
    text_columns = [
        "opened_at",
        "last_seen_at",
        "closed_at",
        "status",
        "signal_key",
        "question",
        "outcome",
        "crypto_symbol",
        "crypto_decision",
        "crypto_decision_reasons",
        "close_reason",
    ]

    for col in text_columns:
        if col not in trades.columns:
            trades[col] = ""
        trades[col] = trades[col].fillna("").astype("object")

    if "not_aligned_count" not in trades.columns:
        trades["not_aligned_count"] = 0

    trades["not_aligned_count"] = pd.to_numeric(
        trades["not_aligned_count"],
        errors="coerce",
    ).fillna(0).astype(int)

    existing_open_keys = set()
    if not trades.empty and "status" in trades.columns and "signal_key" in trades.columns:
        existing_open_keys = set(
            trades.loc[trades["status"].eq("OPEN"), "signal_key"].astype(str)
        )

    cooldown_blocked_keys = set()

    if (
        not trades.empty
        and reentry_cooldown_minutes > 0
        and {"status", "signal_key", "closed_at"}.issubset(trades.columns)
    ):
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=reentry_cooldown_minutes)

        closed = trades.loc[trades["status"].eq("CLOSED")].copy()
        closed["closed_at_dt"] = pd.to_datetime(
            closed["closed_at"],
            utc=True,
            errors="coerce",
        )

        recent_closed = closed[
            closed["closed_at_dt"].notna()
            & (closed["closed_at_dt"] >= cutoff)
        ]

        cooldown_blocked_keys = set(recent_closed["signal_key"].astype(str))

    new_trades = []
    entry_filter_blocked_count = 0

    open_trades_count = 0
    open_exposure_usd = 0.0

    if not trades.empty and "status" in trades.columns:
        open_trades = trades[trades["status"].eq("OPEN")]
        open_trades_count = len(open_trades)

        if "trade_usd" in open_trades.columns:
            open_exposure_usd = float(open_trades["trade_usd"].fillna(0).sum())

    buys = snapshot[snapshot["crypto_decision"].eq("CRYPTO_BUY_FAIR_EDGE")].copy()

    if "fair_edge_to_ask" in buys.columns:
        buys = buys.sort_values("fair_edge_to_ask", ascending=False, na_position="last")

    confirmation_blocked_count = 0

    def previous_signal_observations(key: str) -> int:
        if signal_journal.empty or "signal_key" not in signal_journal.columns:
            return 0

        journal = signal_journal.copy()

        if "observed_at" in journal.columns:
            journal["observed_at_dt"] = pd.to_datetime(
                journal["observed_at"],
                utc=True,
                errors="coerce",
            )
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=confirmation_lookback_minutes)
            journal = journal[
                journal["observed_at_dt"].notna()
                & (journal["observed_at_dt"] >= cutoff)
            ]

        return int(journal["signal_key"].fillna("").astype(str).eq(key).sum())

    def is_signal_confirmed(key: str) -> bool:
        if not require_signal_confirmation:
            return True

        # +1 cuenta la señal del snapshot actual.
        return previous_signal_observations(key) + 1 >= confirmation_min_observations

    for _, row in buys.iterrows():
        if len(new_trades) >= max_new_trades_per_cycle:
            break

        if open_trades_count + len(new_trades) >= max_open_trades:
            continue

        if open_exposure_usd + (len(new_trades) + 1) * trade_usd > max_exposure_usd:
            continue
        key = signal_key(row)

        if key in existing_open_keys:
            continue

        if key in cooldown_blocked_keys:
            continue

        if not is_signal_confirmed(key):
            confirmation_blocked_count += 1
            continue

        ask = safe_float(row.get("best_ask"))
        bid = safe_float(row.get("best_bid"))
        spread = safe_float(row.get("spread"))
        fair_edge = safe_float(row.get("fair_edge_to_ask"))
        orderbook_score = safe_float(row.get("score"))

        if ask is None or ask <= 0:
            continue

        if ask > max_entry_ask:
            entry_filter_blocked_count += 1
            continue

        if spread is not None and spread > max_entry_spread:
            entry_filter_blocked_count += 1
            continue

        if fair_edge is None or fair_edge < min_entry_fair_edge:
            entry_filter_blocked_count += 1
            continue

        if orderbook_score is None or orderbook_score < min_entry_score:
            entry_filter_blocked_count += 1
            continue

        shares = trade_usd / ask
        current_value = shares * bid if bid is not None else None
        pnl_usd = current_value - trade_usd if current_value is not None else None
        pnl_pct = ((bid - ask) / ask * 100) if bid is not None else None

        new_trades.append(
            {
                "opened_at": now_iso(),
                "last_seen_at": now_iso(),
                "closed_at": "",
                "status": "OPEN",
                "signal_key": key,
                "question": row.get("question"),
                "outcome": row.get("outcome"),
                "crypto_symbol": row.get("crypto_symbol"),
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
                "binance_spot_price": row.get("binance_spot_price"),
                "threshold_price": row.get("threshold_price"),
                "fair_probability": row.get("fair_probability"),
                "fair_edge_to_ask": row.get("fair_edge_to_ask"),
                "crypto_decision": row.get("crypto_decision"),
                "crypto_decision_reasons": row.get("crypto_decision_reasons"),
                "close_reason": "",
                "not_aligned_count": 0,
            }
        )

    if trades.empty:
        trades = pd.DataFrame(new_trades)
    elif new_trades:
        trades = pd.concat([trades, pd.DataFrame(new_trades)], ignore_index=True)

    if not trades.empty:
        latest_by_key = {signal_key(row): row for _, row in snapshot.iterrows()}

        for idx, trade in trades[trades["status"].eq("OPEN")].iterrows():
            key = str(trade["signal_key"])
            latest = latest_by_key.get(key)

            if latest is None:
                continue

            bid = safe_float(latest.get("best_bid"))
            ask = safe_float(latest.get("best_ask"))
            entry = safe_float(trade.get("entry_price"))
            shares = safe_float(trade.get("shares"))
            take_profit_price = safe_float(trade.get("take_profit_price"))
            stop_loss_price = safe_float(trade.get("stop_loss_price"))

            trades.loc[idx, "last_seen_at"] = now_iso()

            if bid is not None:
                trades.loc[idx, "current_bid"] = bid

            if ask is not None:
                trades.loc[idx, "current_ask"] = ask

            if bid is not None and shares is not None and entry is not None:
                current_value = shares * bid
                trades.loc[idx, "current_value_usd"] = current_value
                trades.loc[idx, "pnl_usd"] = current_value - float(trade.get("trade_usd", trade_usd))
                trades.loc[idx, "pnl_pct"] = ((bid - entry) / entry) * 100

            latest_alignment = str(latest.get("crypto_alignment") or "")
            latest_decision = str(latest.get("crypto_decision") or "")

            not_aligned_now = (
                close_on_binance_not_aligned
                and latest_alignment != "ALIGNED"
                and latest_decision != "CRYPTO_BUY_FAIR_EDGE"
            )

            if not_aligned_now:
                current_not_aligned_count = int(trades.loc[idx, "not_aligned_count"] or 0) + 1
                trades.loc[idx, "not_aligned_count"] = current_not_aligned_count
            else:
                current_not_aligned_count = 0
                trades.loc[idx, "not_aligned_count"] = 0

            if (
                close_on_binance_not_aligned
                and current_not_aligned_count >= exit_confirmation_cycles
            ):
                trades.loc[idx, "status"] = "CLOSED"
                trades.loc[idx, "closed_at"] = now_iso()
                trades.loc[idx, "close_reason"] = "RISK_EXIT_BINANCE_NOT_ALIGNED"

            elif bid is not None and take_profit_price is not None and bid >= take_profit_price:
                trades.loc[idx, "status"] = "CLOSED"
                trades.loc[idx, "closed_at"] = now_iso()
                trades.loc[idx, "close_reason"] = "TAKE_PROFIT"

            elif bid is not None and stop_loss_price is not None and bid <= stop_loss_price:
                trades.loc[idx, "status"] = "CLOSED"
                trades.loc[idx, "closed_at"] = now_iso()
                trades.loc[idx, "close_reason"] = "STOP_LOSS"

    trades.to_csv(trades_path, index=False)

    open_count = 0 if trades.empty else int(trades["status"].eq("OPEN").sum())
    closed_count = 0 if trades.empty else int(trades["status"].eq("CLOSED").sum())

    print("\n=== PAPER EXECUTION ===")
    print(f"Nuevas entradas paper: {len(new_trades)}")
    print(f"Posiciones abiertas: {open_count}")
    print(f"Posiciones cerradas: {closed_count}")
    print(f"Exposición máxima permitida: ${max_exposure_usd:.2f}")
    print(f"Máximo posiciones abiertas: {max_open_trades}")
    print(f"Máximo nuevas entradas/ciclo: {max_new_trades_per_cycle}")
    print(f"Cerrar si Binance pierde alineación: {close_on_binance_not_aligned}")
    print(f"Confirmación de salida: {exit_confirmation_cycles} ciclos")
    print(f"Cooldown reentrada: {reentry_cooldown_minutes} min")
    print(f"Señales bloqueadas por cooldown: {len(cooldown_blocked_keys)}")
    print(f"Confirmación requerida: {require_signal_confirmation}")
    print(f"Confirmación mínima: {confirmation_min_observations} observaciones / {confirmation_lookback_minutes} min")
    print(f"Señales bloqueadas por falta de confirmación: {confirmation_blocked_count}")
    print(f"Filtro entrada ask máximo: {max_entry_ask}")
    print(f"Filtro entrada spread máximo: {max_entry_spread}")
    print(f"Filtro entrada edge mínimo: {min_entry_fair_edge}")
    print(f"Filtro entrada score mínimo: {min_entry_score}")
    print(f"Señales bloqueadas por filtros de entrada: {entry_filter_blocked_count}")
    print(f"Archivo: {trades_path}")

    if not trades.empty:
        cols = [
            "status",
            "crypto_symbol",
            "outcome",
            "entry_price",
            "current_bid",
            "current_ask",
            "trade_usd",
            "current_value_usd",
            "pnl_usd",
            "pnl_pct",
            "take_profit_price",
            "stop_loss_price",
            "close_reason",
            "question",
        ]
        cols = [c for c in cols if c in trades.columns]
        print(trades.tail(10)[cols].to_string(index=False))


if __name__ == "__main__":
    main()
