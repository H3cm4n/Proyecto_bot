from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data.polymarket_gamma import (
    get_active_events,
    extract_market_rows,
    get_active_markets,
    extract_direct_market_rows,
)


TERMS = [
    "up or down",
    "updown",
    "up/down",
    "5m",
    "15m",
    "15-min",
    "15 minute",
    "hourly",
]


ASSETS = [
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "solana",
    "sol",
    "xrp",
]


def text_of(row: dict) -> str:
    parts = [
        row.get("question"),
        row.get("title"),
        row.get("slug"),
        row.get("description"),
    ]
    return " ".join(str(p or "") for p in parts).lower()


def matches(row: dict) -> bool:
    text = text_of(row)
    return any(asset in text for asset in ASSETS) and any(term in text for term in TERMS)


def show_rows(label: str, rows: list[dict]) -> None:
    hits = [row for row in rows if matches(row)]

    print("\n" + "=" * 80)
    print(label)
    print("Filas totales:", len(rows))
    print("Hits Up/Down activos:", len(hits))

    for i, row in enumerate(hits[:50], start=1):
        print("\n#", i)
        print("question:", row.get("question"))
        print("title:", row.get("title"))
        print("slug:", row.get("slug"))
        print("outcome:", row.get("outcome"))
        print("best_bid:", row.get("best_bid"))
        print("best_ask:", row.get("best_ask"))
        print("token_id:", row.get("token_id"))


def main() -> None:
    print("Buscando eventos activos...")
    events = get_active_events(limit=1000)
    event_rows = extract_market_rows(events)
    show_rows("ACTIVE EVENTS", event_rows)

    print("\nBuscando mercados activos directos...")
    markets = get_active_markets(limit=1000)
    market_rows = extract_direct_market_rows(markets)
    show_rows("ACTIVE MARKETS", market_rows)


if __name__ == "__main__":
    main()
