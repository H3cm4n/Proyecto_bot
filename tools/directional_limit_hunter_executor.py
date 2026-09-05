"""
tools/directional_limit_hunter_executor.py
Ejecutor v1.5 con PaperExecutor y registro atómico de PnL en CSV.
"""

import sys
import json
import time
from executors.paper_executor import PaperExecutor
from core.logger import PnLLogger

executor = PaperExecutor(max_open_trades=1, max_pending_orders=1, grace_cycles=3)
logger = PnLLogger()

def run_execution_cycle(candidates: list, market_snapshot: dict):
    # 1. Procesar nuevas señales
    for candidate in candidates:
        res = executor.process_signal(candidate)
        if res.get("status") == "PENDING_CREATED":
            sys.stderr.write(f"[v1.5] Orden PENDING creada: {res['match_key']}
")

    # 2. Actualizar estado de órdenes y evaluar ejecuciones/cierres
    initial_history_len = len(executor.trade_history)
    executor.update_orders_and_trades(market_snapshot)

    # 3. Registrar en CSV si hubo trades cerrados en este ciclo
    if len(executor.trade_history) > initial_history_len:
        new_trades = executor.trade_history[initial_history_len:]
        for trade in new_trades:
            logger.log_trade(trade)
            sys.stderr.write(f"[v1.5] Trade CERRADO logged en CSV: {trade['match_key']} | PnL: {trade['pnl_pct']*100}%
")

    # 4. Mostrar estadísticas acumuladas actuales
    stats = logger.calculate_stats()
    return {
        "pending_orders": len(executor.pending_orders),
        "open_trades": len(executor.open_trades),
        "stats": stats
    }

if __name__ == "__main__":
    print("[v1.5] Directional Limit Hunter Executor inicializado en modo Paper Trading.")
