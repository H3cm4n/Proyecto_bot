from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data.polymarket_gamma import get_active_markets


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


def safe_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def parse_dt(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
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


def is_tradeable(market: dict) -> tuple[bool, str]:
    now = datetime.now(timezone.utc)

    active = market.get("active") is True
    closed = market.get("closed") is True
    archived = market.get("archived") is True
    ready = market.get("ready") is True
    funded = market.get("funded") is True
    enable_orderbook = market.get("enableOrderBook") is True

    end_date = parse_dt(market.get("endDate") or market.get("endDateIso"))
    event_start = parse_dt(market.get("eventStartTime"))

    liquidity = safe_float(market.get("liquidityNum") or market.get("liquidity"))
    volume = safe_float(market.get("volumeNum") or market.get("volume"))
    best_bid = safe_float(market.get("bestBid"))
    best_ask = safe_float(market.get("bestAsk"))
    spread = safe_float(market.get("spread"))

    clob_token_ids = market.get("clobTokenIds")

    reasons = []

    if not active:
        reasons.append("NOT_ACTIVE")
    if closed:
        reasons.append("CLOSED")
    if archived:
        reasons.append("ARCHIVED")
    if not ready:
        reasons.append("NOT_READY")
    if not funded:
        reasons.append("NOT_FUNDED")
    if not enable_orderbook:
        reasons.append("ORDERBOOK_DISABLED")
    if end_date is not None and end_date <= now:
        reasons.append("END_DATE_PAST")
    if event_start is not None and event_start > now:
        reasons.append("NOT_STARTED_YET")
    if liquidity is None or liquidity <= 0:
        reasons.append("NO_LIQUIDITY")
    if volume is None or volume <= 0:
        reasons.append("NO_VOLUME")
    if best_bid is None or best_bid <= 0:
        reasons.append("NO_BID")
    if best_ask is None or best_ask >= 1:
        reasons.append("NO_ASK")
    if spread is None or spread >= 0.10:
        reasons.append("SPREAD_TOO_WIDE")
    if not clob_token_ids:
        reasons.append("NO_CLOB_TOKEN_IDS")

    return len(reasons) == 0, ",".join(reasons) if reasons else "TRADEABLE"


def main() -> None:
    rows = []
    updown_rows = []
    tradeable_rows = []

    for offset in range(0, 2200, 100):
        print(f"Descargando offset={offset}...")

        try:
            markets = get_active_markets(limit=100, offset=offset)
        except Exception as exc:
            print(f"ERROR offset={offset}: {exc}")
            break

        if not markets:
            break

        for market in markets:
            if not isinstance(market, dict):
                continue

            symbol = infer_symbol(market)
            if not symbol:
                continue

            if not is_updown(market):
                continue

            ok, reason = is_tradeable(market)

            row = {
                "symbol": symbol,
                "question": market.get("question"),
                "slug": market.get("slug"),
                "active": market.get("active"),
                "closed": market.get("closed"),
                "archived": market.get("archived"),
                "ready": market.get("ready"),
                "funded": market.get("funded"),
                "enableOrderBook": market.get("enableOrderBook"),
                "restricted": market.get("restricted"),
                "endDate": market.get("endDate"),
                "eventStartTime": market.get("eventStartTime"),
                "liquidity": market.get("liquidity"),
                "liquidityNum": market.get("liquidityNum"),
                "volume": market.get("volume"),
                "volumeNum": market.get("volumeNum"),
                "bestBid": market.get("bestBid"),
                "bestAsk": market.get("bestAsk"),
                "spread": market.get("spread"),
                "clobTokenIds": market.get("clobTokenIds"),
                "tradeable": ok,
                "tradeable_reason": reason,
            }

            rows.append(row)
            updown_rows.append(row)

            if ok:
                tradeable_rows.append(row)

        time.sleep(0.15)

    print("\n=== UP/DOWN DISCOVERY ===")
    print(f"Up/Down encontrados: {len(updown_rows)}")
    print(f"Tradeables: {len(tradeable_rows)}")

    print("\n=== RAZONES DE NO TRADEABLE ===")
    reason_counts = {}

    for row in updown_rows:
        for reason in str(row["tradeable_reason"]).split(","):
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"{reason}: {count}")

    print("\n=== TRADEABLES ===")
    for row in tradeable_rows[:30]:
        print(json.dumps(row, indent=2, ensure_ascii=False))

    out = Path("data/tradeable_updown_candidates.csv")
    out.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(rows[0].keys()) if rows else [
        "symbol",
        "question",
        "slug",
        "tradeable",
        "tradeable_reason",
    ]

    with out.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"\nArchivo guardado: {out}")


if __name__ == "__main__":
    main()
