from __future__ import annotations

from pathlib import Path
import csv
import json
import re
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data.polymarket_gamma import get_active_markets


CLOB_BASE_URL = "https://clob.polymarket.com"

ASSET_TERMS = {
    "BTCUSDT": ["bitcoin", "btc"],
    "ETHUSDT": ["ethereum", "eth"],
    "SOLUSDT": ["solana", "sol"],
    "XRPUSDT": ["xrp"],
}

UPDOWN_TERMS = [
    "up or down",
    "updown",
    "up/down",
    "up-down",
    "up down",
]


def parse_json_field(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            return []

    return []


def safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def text_of(market: dict) -> str:
    parts = [
        market.get("question"),
        market.get("title"),
        market.get("slug"),
        market.get("description"),
    ]

    events = market.get("events")
    if isinstance(events, list):
        for event in events:
            if isinstance(event, dict):
                parts.extend([
                    event.get("title"),
                    event.get("slug"),
                    event.get("description"),
                    event.get("seriesSlug"),
                ])

    return " ".join(str(p or "") for p in parts).lower()


def contains_term(text: str, term: str) -> bool:
    term = term.lower()

    if term.isalnum() and len(term) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None

    return term in text


def infer_symbol(market: dict) -> str | None:
    text = text_of(market)

    for symbol, terms in ASSET_TERMS.items():
        if any(contains_term(text, term) for term in terms):
            return symbol

    return None


def is_updown(market: dict) -> bool:
    text = text_of(market)
    return any(term in text for term in UPDOWN_TERMS)


def get_book(token_id: str) -> dict:
    response = requests.get(
        f"{CLOB_BASE_URL}/book",
        params={"token_id": token_id},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    if isinstance(data, dict):
        return data

    return {}


def best_book_prices(book: dict) -> tuple[float | None, float | None, int, int]:
    bids = book.get("bids") or []
    asks = book.get("asks") or []

    bid_prices = []
    ask_prices = []

    for bid in bids:
        if isinstance(bid, dict):
            price = safe_float(bid.get("price"))
        elif isinstance(bid, list) and bid:
            price = safe_float(bid[0])
        else:
            price = None

        if price is not None:
            bid_prices.append(price)

    for ask in asks:
        if isinstance(ask, dict):
            price = safe_float(ask.get("price"))
        elif isinstance(ask, list) and ask:
            price = safe_float(ask[0])
        else:
            price = None

        if price is not None:
            ask_prices.append(price)

    best_bid = max(bid_prices) if bid_prices else None
    best_ask = min(ask_prices) if ask_prices else None

    return best_bid, best_ask, len(bids), len(asks)


def main() -> None:
    rows = []
    found_markets = 0

    for offset in range(0, 2100, 100):
        print(f"Descargando offset={offset}...")

        try:
            markets = get_active_markets(limit=100, offset=offset)
        except Exception as exc:
            print(f"ERROR offset={offset}: {exc}")
            break

        for market in markets:
            if not isinstance(market, dict):
                continue

            symbol = infer_symbol(market)
            if not symbol:
                continue

            if not is_updown(market):
                continue

            found_markets += 1

            outcomes = parse_json_field(market.get("outcomes"))
            token_ids = parse_json_field(market.get("clobTokenIds"))

            for idx, token_id in enumerate(token_ids):
                outcome = outcomes[idx] if idx < len(outcomes) else f"outcome_{idx}"

                row = {
                    "symbol": symbol,
                    "question": market.get("question"),
                    "slug": market.get("slug"),
                    "outcome": outcome,
                    "token_id": token_id,
                    "gamma_best_bid": market.get("bestBid"),
                    "gamma_best_ask": market.get("bestAsk"),
                    "gamma_spread": market.get("spread"),
                    "ready": market.get("ready"),
                    "funded": market.get("funded"),
                    "enableOrderBook": market.get("enableOrderBook"),
                    "endDate": market.get("endDate"),
                    "eventStartTime": market.get("eventStartTime"),
                    "clob_ok": False,
                    "clob_error": "",
                    "clob_best_bid": None,
                    "clob_best_ask": None,
                    "clob_spread": None,
                    "clob_bid_count": 0,
                    "clob_ask_count": 0,
                }

                try:
                    book = get_book(str(token_id))
                    best_bid, best_ask, bid_count, ask_count = best_book_prices(book)

                    row["clob_ok"] = True
                    row["clob_best_bid"] = best_bid
                    row["clob_best_ask"] = best_ask
                    row["clob_bid_count"] = bid_count
                    row["clob_ask_count"] = ask_count

                    if best_bid is not None and best_ask is not None:
                        row["clob_spread"] = round(best_ask - best_bid, 6)

                except Exception as exc:
                    row["clob_error"] = str(exc)

                rows.append(row)

                print(
                    f"{symbol} {outcome} | "
                    f"gamma {market.get('bestBid')}/{market.get('bestAsk')} | "
                    f"clob {row['clob_best_bid']}/{row['clob_best_ask']} | "
                    f"book {row['clob_bid_count']}/{row['clob_ask_count']} | "
                    f"{market.get('slug')}"
                )

                time.sleep(0.1)

        time.sleep(0.15)

    out = Path("data/updown_clob_probe.csv")
    out.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(rows[0].keys()) if rows else [
        "symbol",
        "question",
        "slug",
        "outcome",
        "token_id",
        "clob_ok",
        "clob_error",
    ]

    with out.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow(row)

    tradeable = [
        row for row in rows
        if row["clob_best_bid"] is not None
        and row["clob_best_ask"] is not None
        and row["clob_best_bid"] > 0
        and row["clob_best_ask"] < 1
    ]

    print("\n=== CLOB PROBE SUMMARY ===")
    print("Up/Down markets encontrados:", found_markets)
    print("Tokens probados:", len(rows))
    print("Tokens con book tradeable:", len(tradeable))
    print("Archivo:", out)


if __name__ == "__main__":
    main()
