from typing import Any
import json
import requests


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


def parse_json_field(value: Any) -> list:
    """
    Algunos campos de Gamma vienen como JSON string:
    '["Yes", "No"]'
    Otros pueden venir como lista real.
    Esta función normaliza ambos casos.
    """
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return []

    return []


def get_active_events(limit: int = 20) -> list[dict[str, Any]]:
    """
    Obtiene eventos activos de Polymarket usando la Gamma API pública.
    No requiere API key ni wallet.
    """
    url = f"{GAMMA_BASE_URL}/events"

    params = {
        "active": "true",
        "closed": "false",
        "limit": limit,
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()

    payload = response.json()

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        return payload.get("events") or payload.get("data") or []

    return []


def extract_market_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convierte eventos/mercados en filas limpias.
    Filtra mercados cerrados o sin orderbook.
    """
    rows = []

    for event in events:
        event_title = event.get("title") or event.get("question") or "Sin título"
        event_slug = event.get("slug", "")
        markets = event.get("markets") or []

        for market in markets:
            active = bool(market.get("active"))
            closed = bool(market.get("closed"))
            enable_orderbook = bool(market.get("enableOrderBook", True))

            outcomes = parse_json_field(market.get("outcomes"))
            outcome_prices = parse_json_field(market.get("outcomePrices"))
            clob_token_ids = parse_json_field(market.get("clobTokenIds"))

            if not active:
                continue

            if closed:
                continue

            if not enable_orderbook:
                continue

            if not clob_token_ids:
                continue

            rows.append(
                {
                    "event_title": event_title,
                    "event_slug": event_slug,
                    "market_id": market.get("id", ""),
                    "question": market.get("question", ""),
                    "slug": market.get("slug", ""),
                    "volume": float(market.get("volume") or 0),
                    "liquidity": float(market.get("liquidity") or 0),
                    "active": active,
                    "closed": closed,
                    "enable_orderbook": enable_orderbook,
                    "condition_id": market.get("conditionId", ""),
                    "outcomes": outcomes,
                    "outcome_prices": outcome_prices,
                    "clob_token_ids": clob_token_ids,
                }
            )

    return rows


def get_active_markets(limit: int = 100, offset: int = 0) -> list[dict]:
    """
    Fetch active markets directly from Gamma /markets.

    This is useful when /events does not surface enough standalone
    short-term or category-specific markets.
    """
    response = requests.get(
        f"{GAMMA_BASE_URL}/markets",
        params={
            "active": "true",
            "closed": "false",
            "limit": limit,
            "offset": offset,
        },
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("markets", "data", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    return []


def extract_direct_market_rows(markets: list[dict]) -> list[dict]:
    """
    Normalize Gamma /markets rows into the same shape used by scanner.
    """
    rows: list[dict] = []

    for market in markets:
        if not isinstance(market, dict):
            continue

        active = bool(market.get("active", True))
        closed = bool(market.get("closed", False))
        archived = bool(market.get("archived", False))

        if not active or closed or archived:
            continue

        question = (
            market.get("question")
            or market.get("title")
            or market.get("groupItemTitle")
            or ""
        )

        if not question:
            continue

        outcomes = parse_json_field(market.get("outcomes"))
        outcome_prices = parse_json_field(market.get("outcomePrices"))
        clob_token_ids = parse_json_field(market.get("clobTokenIds"))

        if not outcomes or not clob_token_ids:
            continue

        rows.append(
            {
                "question": question,
                "title": market.get("title") or question,
                "slug": market.get("slug") or "",
                "condition_id": market.get("conditionId") or market.get("condition_id") or "",
                "market_id": market.get("id") or "",
                "event_slug": market.get("eventSlug") or "",
                "outcomes": outcomes,
                "outcome_prices": outcome_prices,
                "clob_token_ids": clob_token_ids,
                "volume": market.get("volume") or market.get("volumeNum") or 0,
                "liquidity": market.get("liquidity") or market.get("liquidityNum") or 0,
                "end_date": market.get("endDate") or market.get("end_date") or "",
                "start_date": market.get("startDate") or market.get("start_date") or "",
            }
        )

    return rows

