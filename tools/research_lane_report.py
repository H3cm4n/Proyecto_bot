from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.signals.research_lanes import classify_research_lane, flow_support_label, safe_str


SNAPSHOT_PATH = Path("data/crypto_signal_snapshot_fair_value.csv")
FLOW_PATH = Path("data/binance_flow_snapshot.csv")
OUT = Path("data/research_lane_snapshot.csv")


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


def main() -> None:
    snapshot_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SNAPSHOT_PATH

    print("\n=== RESEARCH LANE REPORT ===")

    if not snapshot_path.exists():
        print(f"No existe snapshot: {snapshot_path}")
        return

    try:
        df = pd.read_csv(snapshot_path)
    except pd.errors.EmptyDataError:
        print("Snapshot vacío.")
        return

    if df.empty:
        print("No hay filas.")
        return

    flow_by_symbol = load_flow()
    rows = []

    for _, row in df.iterrows():
        classified = classify_research_lane(row)

        if not classified["research_pass"]:
            continue

        symbol = safe_str(row.get("crypto_symbol")).strip().upper()
        flow_row = flow_by_symbol.get(symbol, {})
        flow_bias = safe_str(flow_row.get("flow_bias")).upper()
        trade_direction = classified["trade_direction"]

        out = row.to_dict()
        out["research_lane"] = classified["research_lane"]
        out["research_reason"] = classified["research_reason"]
        out["trade_direction"] = trade_direction
        out["flow_bias"] = flow_bias
        out["flow_support"] = flow_support_label(flow_bias, trade_direction)
        out["depth_imbalance"] = flow_row.get("depth_imbalance")
        rows.append(out)

    if not rows:
        print("No hay candidatos research BTC_CHEAP_CONVEX ahora.")
        return

    out_df = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(OUT, index=False)

    print(f"Candidatos research: {len(out_df)}")
    print(f"Archivo: {OUT}")

    cols = [
        "research_lane",
        "crypto_symbol",
        "outcome",
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_edge_to_ask",
        "crypto_decision",
        "crypto_alignment",
        "binance_bias",
        "flow_bias",
        "flow_support",
        "question",
    ]
    cols = [col for col in cols if col in out_df.columns]

    print(out_df[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
