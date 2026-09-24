"""
tools/ascii_chart.py
Monitor de precios Spot en tiempo real con representación gráfica ASCII para la terminal.
"""

import sys
import time
import json
import urllib.request

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
HISTORY = {"BTCUSDT": [], "ETHUSDT": []}
MAX_HIST = 15


def fetch_prices():
    prices = {}
    for sym in SYMBOLS:
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={sym}"
            req = urllib.request.urlopen(url, timeout=2)
            data = json.loads(req.read().decode())
            prices[sym] = float(data["price"])
        except Exception:
            prices[sym] = 0.0
    return prices


def render_ascii_sparkline(prices_list):
    if not prices_list or len(prices_list) < 2:
        return "Cargando datos..."

    min_p, max_p = min(prices_list), max(prices_list)
    bars = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]

    if max_p == min_p:
        return bars[0] * len(prices_list)

    normalized = [
        int((p - min_p) / (max_p - min_p) * (len(bars) - 1))
        for p in prices_list
    ]
    return "".join(bars[idx] for idx in normalized)


def main():
    print("\033[2J\033[H", end="")  # Limpiar pantalla
    print("=== MONITOR SPOT EN TIEMPO REAL (BTC / ETH) ===")

    while True:
        prices = fetch_prices()
        for sym, p in prices.items():
            if p > 0:
                HISTORY[sym].append(p)
                if len(HISTORY[sym]) > MAX_HIST:
                    HISTORY[sym].pop(0)

        print("\033[H", end="")
        print("=== MONITOR SPOT EN TIEMPO REAL (BINANCE) ===\n")

        for sym in SYMBOLS:
            hist = HISTORY[sym]
            curr_p = prices.get(sym, 0.0)
            spark = render_ascii_sparkline(hist)
            display_name = "BTC" if "BTC" in sym else "ETH"
            print(f"[{display_name}] ${curr_p:10.2f}  | Gráfica: [{spark:<15}]")

        print(f"\nÚltima actualización: {time.strftime('%H:%M:%S')}")
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
