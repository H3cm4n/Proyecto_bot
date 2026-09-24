"""
services/risk_manager.py
Módulo de gestión de riesgos para validar límites de capital, tamaño de orden y liquidez en libro.
"""

import sys
import requests


class RiskManager:
    def __init__(self, max_position_pct=0.05, max_order_usd=50.0, min_depth_usd=10.0):
        self.max_position_pct = max_position_pct
        self.max_order_usd = max_order_usd
        self.min_depth_usd = min_depth_usd  # Mínimo de liquidez requerida en el libro
        self.clob_book_url = "https://clob.polymarket.com/book"

    def check_orderbook_depth(self, token_id: str, side: str, required_size: float) -> tuple:
        """
        Consulta el libro de órdenes del CLOB de Polymarket y verifica si hay liquidez suficiente.
        """
        if not token_id or token_id == "N/A":
            return True, "SKIPPED_NO_TOKEN"

        try:
            params = {"token_id": token_id}
            res = requests.get(self.clob_book_url, params=params, timeout=5)
            if res.status_code == 200:
                book = res.json()
                # Para comprar (BUY/YES) revisamos ASKS; para vender revisamos BIDS
                orders = book.get("asks", []) if side.upper() in ["BUY", "YES"] else book.get("bids", [])
                
                total_available_size = sum(float(o.get("size", 0)) for o in orders[:5])
                
                if total_available_size < required_size:
                    return False, f"INSUFFICIENT_DEPTH (Disponible: {total_available_size:.2f}, Requerido: {required_size:.2f})"
                return True, "DEPTH_OK"
        except Exception as e:
            # Si falla la llamada por timeout o red, se permite el paso con aviso
            return True, f"DEPTH_CHECK_WARNING ({e})"

        return True, "DEPTH_OK"

    def validate_trade(self, signal: dict, balance_usd: float = 1000.0) -> tuple:
        """
        Valida las reglas de riesgo operacionales y la profundidad del libro de órdenes.
        """
        price = float(signal.get("price", 0.0))
        size = float(signal.get("size", 0.0))
        token_id = signal.get("token_id", "N/A")
        outcome = signal.get("outcome", "YES")

        amount_usd = signal.get("amount_usd", price * size)

        # 1. Regla: Tamaño máximo por orden individual
        if amount_usd > self.max_order_usd:
            return False, f"EXCEEDS_MAX_ORDER_USD (${amount_usd:.2f} > ${self.max_order_usd:.2f})"

        # 2. Regla: Porcentaje máximo del balance del portafolio
        max_allowed_usd = balance_usd * self.max_position_pct
        if amount_usd > max_allowed_usd:
            return False, f"EXCEEDS_PORTFOLIO_LIMIT (${amount_usd:.2f} > ${max_allowed_usd:.2f})"

        # 3. Regla: Verificación de profundidad del libro (Orderbook Depth)
        if token_id != "N/A":
            depth_ok, depth_reason = self.check_orderbook_depth(token_id, outcome, size)
            if not depth_ok:
                return False, depth_reason

        return True, "PASSED"
