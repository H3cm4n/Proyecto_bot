from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import csv
import json


ROUTER_DECISION_PATH = Path("data/market_router_last.json")
JOURNAL_PATH = Path("data/market_router_journal.csv")


FIELDNAMES = [
    "timestamp_utc",
    "route",
    "reason",
    "updown_rows",
    "updown_tradeable",
    "above_rows",
    "above_tradeable",
    "best_symbol",
    "best_outcome",
    "best_decision",
    "best_question",
    "best_slug",
    "best_bid",
    "best_ask",
    "best_spread",
    "best_edge",
    "best_token_id",
]


def load_decision() -> dict:
    if not ROUTER_DECISION_PATH.exists():
        return {
            "route": "NONE",
            "reason": "market_router_last.json no existe",
            "best": {},
        }

    try:
        return json.loads(ROUTER_DECISION_PATH.read_text())
    except Exception as exc:
        return {
            "route": "NONE",
            "reason": f"error leyendo router json: {exc}",
            "best": {},
        }


def main() -> None:
    data = load_decision()
    best = data.get("best") or {}

    row = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "route": data.get("route") or "NONE",
        "reason": data.get("reason") or "",
        "updown_rows": data.get("updown_rows", 0),
        "updown_tradeable": data.get("updown_tradeable", 0),
        "above_rows": data.get("above_rows", 0),
        "above_tradeable": data.get("above_tradeable", 0),
        "best_symbol": best.get("symbol") or best.get("crypto_symbol") or "",
        "best_outcome": best.get("outcome") or "",
        "best_decision": best.get("crypto_decision") or "",
        "best_question": best.get("question") or "",
        "best_slug": best.get("slug") or "",
        "best_bid": best.get("clob_best_bid") or best.get("best_bid") or "",
        "best_ask": best.get("clob_best_ask") or best.get("best_ask") or "",
        "best_spread": best.get("clob_spread") or best.get("spread") or "",
        "best_edge": best.get("fair_edge_to_ask") or "",
        "best_token_id": best.get("token_id") or "",
    }

    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not JOURNAL_PATH.exists()

    with JOURNAL_PATH.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)

        if write_header:
            writer.writeheader()

        writer.writerow(row)

    print(
        "Router journal actualizado:",
        JOURNAL_PATH,
        "| route:",
        row["route"],
        "| above:",
        row["above_tradeable"],
        "| updown:",
        row["updown_tradeable"],
    )


if __name__ == "__main__":
    main()
