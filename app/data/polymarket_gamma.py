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
