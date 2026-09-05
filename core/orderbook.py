"""
core/orderbook.py
Módulo para simulación realista de ejecuciones (Fill, Slippage y Spread Relativo).
"""

def calculate_relative_spread(best_bid: float, best_ask: float) -> float:
    """Calcula el spread como un porcentaje relativo al mejor ask."""
    if best_ask <= 0:
        return 1.0
    return round((best_ask - best_bid) / best_ask, 4)


def simulate_limit_fill(limit_price: float, best_ask: float, ask_depth: float, target_size: float = 1.0):
    """
    Simula si una orden límite se llena y calcula el precio efectivo con slippage.
    """
    if best_ask > limit_price:
        return {"filled": False, "fill_price": None, "fill_ratio": 0.0}

    effective_price = min(limit_price, best_ask)

    if ask_depth < target_size and ask_depth > 0:
        fill_ratio = ask_depth / target_size
        slippage_penalty = (1.0 - fill_ratio) * 0.01
        effective_price = min(limit_price, effective_price + slippage_penalty)
    else:
        fill_ratio = 1.0

    return {
        "filled": True,
        "fill_price": round(effective_price, 4),
        "fill_ratio": round(fill_ratio, 2)
    }
