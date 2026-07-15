from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


SNAPSHOT_PATH = Path("data/crypto_signal_snapshot_fair_value.csv")
FLOW_PATH = Path("data/binance_flow_snapshot.csv")
ROUTER_PATH = Path("data/market_router_last.json")
OUT = Path("data/candidate_journal.csv")


FIELDNAMES = [
    "observed_at",
    "signal_key",
    "token_id",
    "question",
    "outcome",
    "crypto_symbol",
    "market_bias",
    "binance_bias",
    "crypto_alignment",
    "crypto_decision",
    "crypto_decision_reasons",
    "best_bid",
    "best_ask",
    "spread",
    "score",
    "fair_probability",
    "fair_edge_to_ask",
    "distance_pct",
    "threshold_price",
    "binance_spot_price",
    "flow_bias",
    "depth_imbalance",
    "flow_support",
    "trade_direction",
    "router_route",
    "router_reason",
]


def safe_str(value) -> str:
    if value is None:
        return ""

    text = str(value)

    if text.lower() == "nan":
        return ""

    return text


def signal_key(row: pd.Series) -> str:
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


def infer_trade_direction(question: str, outcome: str) -> str:
    q = safe_str(question).lower()
    o = safe_str(outcome).lower().strip()

    bullish_question = any(
        token in q
        for token in [
            "above",
            "reach",
            "reaches",
            "hit",
            "hits",
            "higher",
            "up",
        ]
    )

    bearish_question = any(
        token in q
        for token in [
            "below",
            "under",
            "dip",
            "dips",
            "lower",
            "down",
        ]
    )

    yes = o in {"yes", "y", "up", "higher"}
    no = o in {"no", "n", "down", "lower"}

    if bullish_question and yes:
        return "BULLISH"

    if bullish_question and no:
        return "BEARISH"

    if bearish_question and yes:
        return "BEARISH"

    if bearish_question and no:
        return "BULLISH"

    if o in {"up", "higher"}:
        return "BULLISH"

    if o in {"down", "lower"}:
        return "BEARISH"

    return "UNKNOWN"


def flow_support_label(flow_bias: str, trade_direction: str) -> str:
    flow_bias = safe_str(flow_bias).upper()
    trade_direction = safe_str(trade_direction).upper()

    if flow_bias == "" or trade_direction == "" or trade_direction == "UNKNOWN":
        return "UNKNOWN"

    if flow_bias == "NEUTRAL":
        return "NEUTRAL"

    if flow_bias == trade_direction:
        return "SUPPORTS"

    return "AGAINST"


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


def load_router() -> dict:
    if not ROUTER_PATH.exists():
        return {}

    try:
        return json.loads(ROUTER_PATH.read_text())
    except Exception:
        return {}


def main() -> None:
    snapshot_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SNAPSHOT_PATH

    if not snapshot_path.exists():
        print(f"No existe snapshot: {snapshot_path}")
        return

    try:
        df = pd.read_csv(snapshot_path)
    except pd.errors.EmptyDataError:
        print("Snapshot vacío.")
        return

    if df.empty:
        print("No hay candidatos para registrar.")
        return

    flow = load_flow()
    router = load_router()

    observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    router_route = safe_str(router.get("route"))
    router_reason = safe_str(router.get("reason"))

    rows = []

    for _, row in df.iterrows():
        symbol = safe_str(row.get("crypto_symbol")).strip().upper()
        flow_row = flow.get(symbol, {})
        flow_bias = safe_str(flow_row.get("flow_bias")).upper()
        trade_direction = infer_trade_direction(
            row.get("question"),
            row.get("outcome"),
        )

        out_row = {
            "observed_at": observed_at,
            "signal_key": signal_key(row),
            "token_id": safe_str(row.get("token_id")),
            "question": safe_str(row.get("question")),
            "outcome": safe_str(row.get("outcome")),
            "crypto_symbol": symbol,
            "market_bias": safe_str(row.get("market_bias")),
            "binance_bias": safe_str(row.get("binance_bias")),
            "crypto_alignment": safe_str(row.get("crypto_alignment")),
            "crypto_decision": safe_str(row.get("crypto_decision")),
            "crypto_decision_reasons": safe_str(row.get("crypto_decision_reasons")),
            "best_bid": row.get("best_bid"),
            "best_ask": row.get("best_ask"),
            "spread": row.get("spread"),
            "score": row.get("score"),
            "fair_probability": row.get("fair_probability"),
            "fair_edge_to_ask": row.get("fair_edge_to_ask"),
            "distance_pct": row.get("distance_pct"),
            "threshold_price": row.get("threshold_price"),
            "binance_spot_price": row.get("binance_spot_price"),
            "flow_bias": flow_bias,
            "depth_imbalance": flow_row.get("depth_imbalance"),
            "flow_support": flow_support_label(flow_bias, trade_direction),
            "trade_direction": trade_direction,
            "router_route": router_route,
            "router_reason": router_reason,
        }

        rows.append(out_row)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_header = not OUT.exists()

    with OUT.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)

        if write_header:
            writer.writeheader()

        writer.writerows(rows)

    print("\n=== CANDIDATE JOURNAL ===")
    print(f"Candidatos registrados: {len(rows)}")
    print(f"Archivo: {OUT}")

    if "crypto_decision" in df.columns:
        print("\nTop decisiones:")
        print(df["crypto_decision"].value_counts(dropna=False).head(10).to_string())


if __name__ == "__main__":
    main()
