from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def score_spread(spread: float) -> int:
    """
    Puntúa qué tan barato es entrar al mercado.
    Menor spread = mejor ejecución.
    """
    if spread <= 0:
        return 0

    if spread <= 0.005:
        return 35

    if spread <= 0.01:
        return 32

    if spread <= 0.02:
        return 28

    if spread <= 0.03:
        return 20

    if spread <= 0.05:
        return 10

    return 0


def score_liquidity(top_liquidity: float) -> int:
    """
    Puntúa la liquidez disponible en el mejor bid/ask.
    Usamos top_liquidity = min(bid_size, ask_size).
    """
    if top_liquidity >= 100:
        return 25

    if top_liquidity >= 50:
        return 20

    if top_liquidity >= 20:
        return 15

    if top_liquidity >= 10:
        return 10

    if top_liquidity >= 5:
        return 5

    return 0


def score_price_zone(mid_price: float) -> int:
    """
    Evita mercados extremadamente cercanos a 0 o 1.
    En extremos hay más riesgo de mala ejecución o poca señal útil.
    """
    if 0.10 <= mid_price <= 0.90:
        return 20

    if 0.05 <= mid_price <= 0.95:
        return 12

    if 0.02 <= mid_price <= 0.98:
        return 6

    return 0


def score_book_balance(bid_size: float, ask_size: float) -> int:
    """
    Puntúa qué tan equilibrado está el top del orderbook.
    Si un lado está muy delgado, la ejecución puede ser fea.
    """
    bigger = max(bid_size, ask_size)
    smaller = min(bid_size, ask_size)

    if bigger <= 0:
        return 0

    ratio = smaller / bigger

    if ratio >= 0.75:
        return 20

    if ratio >= 0.50:
        return 15

    if ratio >= 0.25:
        return 10

    if ratio >= 0.10:
        return 5

    return 0


def grade_score(score: int) -> str:
    if score >= 80:
        return "A"

    if score >= 65:
        return "B"

    if score >= 50:
        return "C"

    if score >= 35:
        return "D"

    return "F"


def action_from_score(score: int) -> str:
    if score >= 80:
        return "PRIORITY_WATCH"

    if score >= 65:
        return "WATCH"

    if score >= 50:
        return "WEAK_WATCH"

    return "IGNORE"


def score_orderbook_row(row: dict[str, Any]) -> dict[str, Any]:
    spread = safe_float(row.get("spread"))
    mid_price = safe_float(row.get("mid_price"))
    bid_size = safe_float(row.get("bid_size"))
    ask_size = safe_float(row.get("ask_size"))
    top_liquidity = safe_float(row.get("top_liquidity"))

    spread_points = score_spread(spread)
    liquidity_points = score_liquidity(top_liquidity)
    price_zone_points = score_price_zone(mid_price)
    balance_points = score_book_balance(bid_size, ask_size)

    total_score = spread_points + liquidity_points + price_zone_points + balance_points

    return {
        "score": total_score,
        "grade": grade_score(total_score),
        "action": action_from_score(total_score),
        "spread_points": spread_points,
        "liquidity_points": liquidity_points,
        "price_zone_points": price_zone_points,
        "balance_points": balance_points,
    }
