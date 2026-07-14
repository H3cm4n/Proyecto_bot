from __future__ import annotations

from pathlib import Path
import csv
import re
import sys
import time

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
    "up-down",
    "up down",
    "5m",
    "15m",
    "15-min",
    "15 minute",
    "hourly",
]


ASSET_TERMS = {
    "BTCUSDT": ["bitcoin", "btc"],
    "ETHUSDT": ["ethereum", "eth"],
    "SOLUSDT": ["solana", "sol"],
    "XRPUSDT": ["xrp"],
}


def normalize(value) -> str:
    return str(value or "").lower()


def text_of(row: dict) -> str:
    parts = [
        row.get("question"),
        row.get("title"),
        row.get("slug"),
        row.get("description"),
        row.get("event_title"),
    ]
    return " ".join(str(p or "") for p in parts).lower()


def contains_term(text: str, term: str) -> bool:
    term = term.lower()

    # Evita falsos positivos tipo "sol" dentro de "resolution".
    if term.isalnum() and len(term) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None

    return term in text


def asset_symbol(row: dict) -> str | None:
    text = text_of(row)

    for symbol, terms in ASSET_TERMS.items():
        if any(contains_term(text, term) for term in terms):
            return symbol

    return None


def is_updown(row: dict) -> bool:
    text = text_of(row)
    return any(contains_term(text, term) for term in TERMS)


def row_key(row: dict) -> str:
    return "|".join(
        str(row.get(key) or "")
        for key in ("token_id", "condition_id", "question", "outcome")
    )


def collect_active_market_rows(page_limit: int = 100, max_pages: int = 50) -> list[dict]:
    rows: list[dict] = []
    seen_rows: set[str] = set()
    seen_page_signatures: set[str] = set()

    for page in range(max_pages):
        offset = page * page_limit
        print(f"Descargando mercados activos offset={offset} limit={page_limit}...")

        try:
            markets = get_active_markets(limit=page_limit, offset=offset)
        except Exception as exc:
            print(f"ERROR offset={offset}: {exc}")
            break

        if not markets:
            print("Sin más mercados.")
            break

        page_signature = "|".join(
            str(m.get("id") or m.get("conditionId") or m.get("question") or "")
            for m in markets[:10]
            if isinstance(m, dict)
        )

        if page_signature in seen_page_signatures:
            print("La API parece repetir la misma página; deteniendo paginación.")
            break

        seen_page_signatures.add(page_signature)

        extracted = extract_direct_market_rows(markets)

        for row in extracted:
            key = row_key(row)
            if key in seen_rows:
                continue
            seen_rows.add(key)
            rows.append(row)

        if len(markets) < page_limit:
            print("Última página detectada.")
            break

        time.sleep(0.15)

    return rows


def show_rows(label: str, rows: list[dict]) -> None:
    crypto_rows = []
    updown_rows = []

    for row in rows:
        symbol = asset_symbol(row)
        if not symbol:
            continue

        enriched = dict(row)
        enriched["matched_symbol"] = symbol
        crypto_rows.append(enriched)

        if is_updown(row):
            updown_rows.append(enriched)

    print("\n" + "=" * 80)
    print(label)
    print("Filas totales:", len(rows))
    print("Crypto candidates activos:", len(crypto_rows))
    print("Hits Up/Down activos:", len(updown_rows))

    print("\n--- TOP UP/DOWN ---")
    for i, row in enumerate(updown_rows[:50], start=1):
        print("\n#", i)
        print("symbol:", row.get("matched_symbol"))
        print("question:", row.get("question"))
        print("title:", row.get("title"))
        print("slug:", row.get("slug"))
        print("outcome:", row.get("outcome"))
        print("best_bid:", row.get("best_bid"))
        print("best_ask:", row.get("best_ask"))
        print("token_id:", row.get("token_id"))

    print("\n--- TOP CRYPTO CANDIDATES ---")
    for i, row in enumerate(crypto_rows[:80], start=1):
        print("\n#", i)
        print("symbol:", row.get("matched_symbol"))
        print("question:", row.get("question"))
        print("title:", row.get("title"))
        print("slug:", row.get("slug"))
        print("outcome:", row.get("outcome"))
        print("best_bid:", row.get("best_bid"))
        print("best_ask:", row.get("best_ask"))

    return crypto_rows, updown_rows


def save_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "matched_symbol",
        "question",
        "title",
        "slug",
        "outcome",
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "token_id",
        "condition_id",
    ]

    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def main() -> None:
    print("Buscando eventos activos...")
    events = get_active_events(limit=1000)
    event_rows = extract_market_rows(events)
    event_crypto_rows, event_updown_rows = show_rows("ACTIVE EVENTS", event_rows)

    print("\nBuscando mercados activos directos con paginación...")
    market_rows = collect_active_market_rows(page_limit=100, max_pages=50)
    market_crypto_rows, market_updown_rows = show_rows("ACTIVE MARKETS PAGINATED", market_rows)

    all_crypto = event_crypto_rows + market_crypto_rows
    all_updown = event_updown_rows + market_updown_rows

    save_rows(Path("data/active_crypto_candidates.csv"), all_crypto)
    save_rows(Path("data/active_updown_candidates.csv"), all_updown)

    print("\n" + "=" * 80)
    print("Archivos guardados:")
    print("data/active_crypto_candidates.csv")
    print("data/active_updown_candidates.csv")
    print(f"Crypto candidates total: {len(all_crypto)}")
    print(f"Up/Down candidates total: {len(all_updown)}")


if __name__ == "__main__":
    main()
