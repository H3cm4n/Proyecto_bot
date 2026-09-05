"""
tools/generate_pnl_report.py
Generador de reportes de rendimiento y PnL por activo para Directional Limit Hunter v1.5.
"""

import os
import csv
import sys
from typing import Dict, List
from core.logger import PnLLogger

def parse_symbol_from_key(match_key: str, condition_id: str) -> str:
    key_upper = match_key.upper()
    if 'BTC' in key_upper:
        return 'BTC'
    elif 'ETH' in key_upper:
        return 'ETH'
    elif 'SOL' in key_upper:
        return 'SOL'
    elif 'XRP' in key_upper:
        return 'XRP'
    return 'OTROS'

def generate_report(csv_path: str = 'data/trade_history.csv'):
    if not os.path.exists(csv_path):
        print(f"[!] No se encontro el archivo de historial en: {csv_path}")
        print("[i] Ejecuta primero ciclos de paper trading para generar registros de operaciones.")
        return

    logger = PnLLogger(output_dir=os.path.dirname(csv_path), filename=os.path.basename(csv_path))
    stats = logger.calculate_stats()

    if stats['total_trades'] == 0:
        print('==================================================')
        print('          REPORTE DE RENDIMIENTO PnL (v1.5)       ')
        print('==================================================')
        print('Sin operaciones cerradas registradas aun.')
        print('==================================================')
        return

    by_asset: Dict[str, Dict] = {}
    durations: List[float] = []

    with open(csv_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            match_key = row.get('match_key', '')
            cond_id = row.get('condition_id', '')
            pnl_pct = float(row.get('pnl_pct', 0.0))
            pnl_usd = float(row.get('pnl_usd', 0.0))
            duration = float(row.get('duration_seconds', 0.0))

            asset = parse_symbol_from_key(match_key, cond_id)
            if asset not in by_asset:
                by_asset[asset] = {'trades': 0, 'wins': 0, 'pnl_usd': 0.0, 'pnl_pct': 0.0}

            by_asset[asset]['trades'] += 1
            if pnl_pct > 0:
                by_asset[asset]['wins'] += 1
            by_asset[asset]['pnl_usd'] += pnl_usd
            by_asset[asset]['pnl_pct'] += pnl_pct
            durations.append(duration)

    avg_duration_min = round((sum(durations) / len(durations)) / 60.0, 2) if durations else 0.0

    print('==================================================')
    print('      REPORTE DE RENDIMIENTO DIRECTIONAL v1.5     ')
    print('==================================================')
    print(f"Total Trades Cerrados : {stats['total_trades']}")
    print(f"Win Rate Global       : {stats['win_rate']*100:.2f}%")
    print(f"PnL Acumulado (USD)   : ${stats['total_pnl_usd']:.2f}")
    print(f"PnL Acumulado (%)     : {stats['total_pnl_pct']*100:.2f}%")
    print(f"Max Drawdown (USD)    : ${stats['max_drawdown']:.2f}")
    print(f"Duracion Promedio     : {avg_duration_min} min")
    print('--------------------------------------------------')
    print('DESGLOSE POR ACTIVO:')
    print(f"{'ACTIVO':<8} | {'TRADES':<7} | {'WIN RATE':<10} | {'PnL (USD)':<10}")
    print('--------------------------------------------------')
    
    for asset, a_stats in by_asset.items():
        wr = (a_stats['wins'] / a_stats['trades']) * 100 if a_stats['trades'] > 0 else 0.0
        print(f"{asset:<8} | {a_stats['trades']:<7} | {wr:<9.1f}% | ${a_stats['pnl_usd']:<9.2f}")

    print('==================================================')

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else 'data/trade_history.csv'
    generate_report(path)
