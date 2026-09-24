"""
services/paper_trading.py
Módulo para simulación de órdenes (Paper Trading) sin usar fondos reales.
Mantiene balance, historial de ejecuciones y almacenamiento en JSON.
"""

import os
import json
import time
import sys


class PaperTradingEngine:
    def __init__(self, initial_balance_usd=1000.0, storage_file="paper_portfolio.json"):
        self.storage_file = storage_file
        self.portfolio = self._load_portfolio(initial_balance_usd)

    def _load_portfolio(self, default_balance: float) -> dict:
        if os.path.exists(self.storage_file):
            try:
                with open(self.storage_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                sys.stderr.write(f"[PAPER-TRADING] Error al cargar portafolio: {e}\n")

        return {
            "balance_usd": default_balance,
            "positions": {},
            "orders": []
        }

    def _save_portfolio(self):
        try:
            with open(self.storage_file, "w") as f:
                json.dump(self.portfolio, f, indent=2)
        except Exception as e:
            sys.stderr.write(f"[PAPER-TRADING] Error al guardar portafolio: {e}\n")

    def execute_order(self, token_id: str, symbol: str, outcome: str, price: float, size: float) -> dict:
        """
        Simula el llenado inmediato de una orden limitada de compra.
        """
        cost_usd = price * size

        if cost_usd > self.portfolio["balance_usd"]:
            return {
                "status": "REJECTED",
                "reason": f"INSUFFICIENT_FUNDS (Costo: ${cost_usd:.2f}, Balance: ${self.portfolio['balance_usd']:.2f})"
            }

        # Deducción de balance simulado
        self.portfolio["balance_usd"] -= cost_usd

        # Actualización de posición
        pos_key = f"{token_id}_{outcome}"
        if pos_key not in self.portfolio["positions"]:
            self.portfolio["positions"][pos_key] = {
                "symbol": symbol,
                "token_id": token_id,
                "outcome": outcome,
                "size": 0.0,
                "avg_price": 0.0
            }

        pos = self.portfolio["positions"][pos_key]
        total_size = pos["size"] + size
        pos["avg_price"] = ((pos["size"] * pos["avg_price"]) + cost_usd) / total_size
        pos["size"] = total_size

        # Registro de orden
        order_record = {
            "order_id": f"PAPER-{int(time.time() * 1000)}",
            "symbol": symbol,
            "token_id": token_id,
            "outcome": outcome,
            "price": price,
            "size": size,
            "cost_usd": cost_usd,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "FILLED"
        }

        self.portfolio["orders"].append(order_record)
        self._save_portfolio()

        return {
            "status": "FILLED",
            "order_id": order_record["order_id"],
            "cost_usd": cost_usd,
            "remaining_balance": self.portfolio["balance_usd"]
        }


if __name__ == "__main__":
    engine = PaperTradingEngine(1000.0)
    res = engine.execute_order("test_token_123", "ETH", "YES", 0.45, 10.0)
    print("Resultado simulación:", json.dumps(res, indent=2))
