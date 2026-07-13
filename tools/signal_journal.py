from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


SNAPSHOT_PATH = "data/crypto_signal_snapshot_fair_value.csv"
TRADES_PATH = "data/paper_trades.csv"
JOURNAL_PATH = "data/signal_journal.csv"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_str(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def signal_key(row: pd.Series) -> str:
    token_id = safe_str(row.get("token_id")).strip()
    if token_id and token_id.lower() != "nan":
        return token_id

    question = safe_str(row.get("question")).strip()
    outcome = safe_str(row.get("outcome")).strip()
    threshold = safe_str(row.get("threshold_price")).strip()
    return f"{question}|{outcome}|{threshold}"


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def build_trade_state(trades: pd.DataFrame) -> dict[str, dict]:
    state: dict[str, dict] = {}

    if trades.empty:
        return state

    for _, row in trades.iterrows():
        # Use the exact key stored by paper_executor first.
        # Recomputing can mismatch when snapshots have token_id but paper trades do not.
        key = safe_str(row.get("signal_key")).strip()

        if not key:
            key = signal_key(row)

        if not key:
            continue

        state[key] = {
            "paper_status": row.get("status", ""),
            "paper_entry_price": row.get("entry_price", ""),
            "paper_current_bid": row.get("current_bid", ""),
            "paper_pnl_usd": row.get("pnl_usd", ""),
            "paper_pnl_pct": row.get("pnl_pct", ""),
            "paper_close_reason": row.get("close_reason", ""),
            "paper_opened_at": row.get("opened_at", ""),
            "paper_closed_at": row.get("closed_at", ""),
        }

    return state


def main() -> None:
    snapshot_path = Path(sys.argv[1] if len(sys.argv) > 1 else SNAPSHOT_PATH)
    trades_path = Path(os.getenv("PAPER_TRADES_PATH", TRADES_PATH))
    journal_path = Path(os.getenv("SIGNAL_JOURNAL_PATH", JOURNAL_PATH))

    include_watch = os.getenv("SIGNAL_JOURNAL_INCLUDE_WATCH", "0") == "1"

    if not snapshot_path.exists():
        raise SystemExit(f"No existe snapshot: {snapshot_path}")

    snapshot = pd.read_csv(snapshot_path)

    if "crypto_decision" not in snapshot.columns:
        raise SystemExit("El snapshot no tiene crypto_decision.")

    decisions = ["CRYPTO_BUY_FAIR_EDGE"]
    if include_watch:
        decisions.append("CRYPTO_WATCH_FAIR_EDGE")

    signals = snapshot[snapshot["crypto_decision"].isin(decisions)].copy()

    if signals.empty:
        print("\n=== SIGNAL JOURNAL ===")
        print("No hay señales BUY/WATCH para registrar.")
        return

    trades = load_csv(trades_path)
    trade_state = build_trade_state(trades)

    observed_at = now_iso()
    journal_rows = []

    for _, row in signals.iterrows():
        key = signal_key(row)
        paper = trade_state.get(key, {})

        journal_rows.append(
            {
                "observed_at": observed_at,
                "signal_key": key,
                "question": row.get("question", ""),
                "outcome": row.get("outcome", ""),
                "crypto_symbol": row.get("crypto_symbol", ""),
                "crypto_alignment": row.get("crypto_alignment", ""),
                "crypto_decision": row.get("crypto_decision", ""),
                "best_bid": row.get("best_bid", ""),
                "best_ask": row.get("best_ask", ""),
                "spread": row.get("spread", ""),
                "score": row.get("score", ""),
                "binance_spot_price": row.get("binance_spot_price", ""),
                "threshold_price": row.get("threshold_price", ""),
                "distance_to_threshold_pct": row.get("distance_to_threshold_pct", ""),
                "fair_probability": row.get("fair_probability", ""),
                "fair_edge_to_ask": row.get("fair_edge_to_ask", ""),
                "crypto_decision_reasons": row.get("crypto_decision_reasons", ""),
                "paper_status": paper.get("paper_status", "NOT_IN_PAPER"),
                "paper_entry_price": paper.get("paper_entry_price", ""),
                "paper_current_bid": paper.get("paper_current_bid", ""),
                "paper_pnl_usd": paper.get("paper_pnl_usd", ""),
                "paper_pnl_pct": paper.get("paper_pnl_pct", ""),
                "paper_close_reason": paper.get("paper_close_reason", ""),
                "paper_opened_at": paper.get("paper_opened_at", ""),
                "paper_closed_at": paper.get("paper_closed_at", ""),
            }
        )

    journal_path.parent.mkdir(parents=True, exist_ok=True)

    new_df = pd.DataFrame(journal_rows)
    old_df = load_csv(journal_path)

    if old_df.empty:
        out = new_df
    else:
        out = pd.concat([old_df, new_df], ignore_index=True)

    out.to_csv(journal_path, index=False)

    print("\n=== SIGNAL JOURNAL ===")
    print(f"Señales registradas en este ciclo: {len(new_df)}")
    print(f"Total señales en journal: {len(out)}")
    print(f"Archivo: {journal_path}")

    cols = [
        "observed_at",
        "crypto_symbol",
        "outcome",
        "best_ask",
        "fair_probability",
        "fair_edge_to_ask",
        "crypto_decision",
        "paper_status",
        "paper_close_reason",
        "question",
    ]
    cols = [c for c in cols if c in new_df.columns]
    print(new_df[cols].to_string(index=False))


if __name__ == "__main__":
    main()
