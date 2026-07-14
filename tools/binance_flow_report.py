from __future__ import annotations

from pathlib import Path
import csv

from app.signals.binance_flow import get_binance_flow_snapshot


OUT = Path("data/binance_flow_snapshot.csv")


def main() -> None:
    rows = get_binance_flow_snapshot(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
        depth_limit=100,
        levels=20,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "symbol",
        "status",
        "flow_bias",
        "best_bid",
        "best_ask",
        "spread",
        "spread_pct",
        "bid_notional_top",
        "ask_notional_top",
        "depth_imbalance",
        "levels",
        "error",
    ]

    with OUT.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})

    print("\n=== BINANCE FLOW REPORT ===")
    for row in rows:
        print(
            f"{row.get('symbol')} | "
            f"{row.get('status')} | "
            f"flow={row.get('flow_bias')} | "
            f"imbalance={row.get('depth_imbalance')} | "
            f"bid_notional={row.get('bid_notional_top')} | "
            f"ask_notional={row.get('ask_notional_top')} | "
            f"spread_pct={row.get('spread_pct')} | "
            f"error={row.get('error') or ''}"
        )

    print(f"\nArchivo: {OUT}")


if __name__ == "__main__":
    main()
