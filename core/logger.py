"""
core/logger.py
Módulo para registrar la ejecución de trades simulados y calcular estadísticas de PnL en CSV.
"""

import os
import csv
import time
from typing import Dict

class PnLLogger:
    def __init__(self, output_dir: str = "data", filename: str = "trade_history.csv"):
        self.output_dir = output_dir
        self.filepath = os.path.join(self.output_dir, filename)
        self._ensure_dir_and_header()

    def _ensure_dir_and_header(self):
        """Asegura que el directorio exista y crea el archivo CSV con encabezados si no existe."""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)

        if not os.path.exists(self.filepath):
            with open(self.filepath, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "match_key",
                    "condition_id",
                    "entry_price",
                    "close_price",
                    "pnl_pct",
                    "pnl_usd",
                    "opened_at",
                    "closed_at",
                    "duration_seconds"
                ])

    def log_trade(self, trade: Dict, trade_size_usd: float = 100.0):
        """Registra un trade cerrado en el archivo CSV."""
        entry_price = trade.get("entry_price", 0.0)
        close_price = trade.get("close_price", 0.0)
        pnl_pct = trade.get("pnl_pct", 0.0)
        pnl_usd = round(pnl_pct * trade_size_usd, 2)
        
        opened_at = trade.get("opened_at", time.time())
        closed_at = trade.get("closed_at", time.time())
        duration = round(closed_at - opened_at, 2)

        with open(self.filepath, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                trade.get("match_key", ""),
                trade.get("condition_id", ""),
                entry_price,
                close_price,
                pnl_pct,
                pnl_usd,
                opened_at,
                closed_at,
                duration
            ])

    def calculate_stats(self) -> Dict:
        """Lee el historial CSV y calcula estadísticas globales de rendimiento."""
        if not os.path.exists(self.filepath):
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_pnl_pct": 0.0,
                "total_pnl_usd": 0.0,
                "max_drawdown": 0.0
            }

        total_trades = 0
        winning_trades = 0
        total_pnl_pct = 0.0
        total_pnl_usd = 0.0
        pnl_series = []

        with open(self.filepath, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pnl_pct = float(row["pnl_pct"])
                pnl_usd = float(row["pnl_usd"])

                total_trades += 1
                if pnl_pct > 0:
                    winning_trades += 1

                total_pnl_pct += pnl_pct
                total_pnl_usd += pnl_usd
                pnl_series.append(total_pnl_usd)

        win_rate = round(winning_trades / total_trades, 4) if total_trades > 0 else 0.0
        
        max_drawdown = 0.0
        peak = 0.0
        for current_pnl in pnl_series:
            if current_pnl > peak:
                peak = current_pnl
            dd = peak - current_pnl
            if dd > max_drawdown:
                max_drawdown = dd

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_pnl_pct": round(total_pnl_pct, 4),
            "total_pnl_usd": round(total_pnl_usd, 2),
            "max_drawdown": round(max_drawdown, 2)
        }
