"""
tools/directional_limit_hunter_executor.py
Ejecutor principal con soporte para Paper Trading (--paper), Trading Real (--real)
y filtro de frecuencia (cooldown) para streaming WebSockets.
"""

import sys
import json
import time
import asyncio
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from services.risk_manager import RiskManager
from services.market_resolver import MarketResolver
from services.price_feed_websocket import PriceFeedWebSocket
from services.paper_trading import PaperTradingEngine
from services.clob_client import PolymarketClobClient

try:
    from rich.console import Console
    from rich.table import Table
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class DirectionalLimitHunterExecutor:
    def __init__(self, mode="paper", cooldown_seconds=10.0):
        self.mode = mode
        self.cooldown_seconds = cooldown_seconds
        self.last_order_time = {}  # Control de cooldown por simbolo
        self.risk_manager = RiskManager()
        self.resolver = MarketResolver()
        self.paper_engine = PaperTradingEngine() if mode == "paper" else None
        self.clob_client = PolymarketClobClient() if mode == "real" else None
        self.console = Console() if RICH_AVAILABLE else None

    def process_signal(self, signal: dict) -> dict:
        symbol = signal.get("symbol", "")
        question = signal.get("question", "")
        outcome = signal.get("outcome", "YES")
        price = float(signal.get("price", 0.0))
        size = float(signal.get("size", 1.0))

        # 1. Resolver token_ids
        tokens = self.resolver.get_market_tokens(question or symbol)
        token_id = tokens.get(outcome, "N/A")
        market_title = tokens.get("question", question)

        # 2. Validar riesgo y profundidad
        balance = self.paper_engine.portfolio["balance_usd"] if self.paper_engine else 1000.0
        signal_payload = {
            "symbol": symbol,
            "price": price,
            "size": size,
            "amount_usd": price * size,
            "token_id": token_id,
            "outcome": outcome
        }
        order_valid, risk_reason = self.risk_manager.validate_trade(signal_payload, balance)

        status = "REJECTED"
        exec_details = ""

        # 3. Enrutamiento de ejecucion
        if order_valid:
            if token_id == "N/A":
                status = "REJECTED"
                exec_details = "FAILED: UNRESOLVED_TOKEN_ID"
            elif self.mode == "paper" and self.paper_engine:
                exec_res = self.paper_engine.execute_order(token_id, symbol, outcome, price, size)
                status = exec_res["status"]
                exec_details = f"Paper ID: {exec_res.get('order_id', 'N/A')} | Bal: ${exec_res.get('remaining_balance', 0):.2f}"
            elif self.mode == "real" and self.clob_client:
                clob_res = self.clob_client.submit_limit_order(token_id, price, size, side="BUY")
                status = clob_res["status"]
                exec_details = f"Polygon Tx/Order: {clob_res.get('order_id', clob_res.get('reason'))}"
        else:
            exec_details = f"REJECTED: {risk_reason}"

        return {
            "symbol": symbol,
            "market": market_title,
            "outcome": outcome,
            "token_id": token_id,
            "price": price,
            "size": size,
            "risk_check": "PASSED" if order_valid else f"FAILED: {risk_reason}",
            "status": status,
            "details": exec_details
        }

    def render_table(self, results: list):
        if RICH_AVAILABLE:
            table = Table(title=f"Polymarket Bot Execution Snapshot [{self.mode.upper()} MODE]")
            table.add_column("#", justify="right")
            table.add_column("Symbol", style="cyan")
            table.add_column("Question / Market", style="magenta")
            table.add_column("Outcome", justify="center")
            table.add_column("Price", justify="right", style="green")
            table.add_column("Risk Check", style="bold yellow")
            table.add_column("Execution Status", style="bold blue")
            table.add_column("Details", style="dim")

            for idx, item in enumerate(results, 1):
                table.add_row(
                    str(idx),
                    item["symbol"],
                    item["market"],
                    item["outcome"],
                    f"${item['price']:.2f}",
                    item["risk_check"],
                    item["status"],
                    item["details"]
                )
            self.console.print(table)
        else:
            print(json.dumps(results, indent=2))

    async def run_live_stream(self, symbols=None):
        symbols = symbols or ["eth", "btc"]
        sys.stderr.write(f"[EXECUTOR] Feed en vivo [{self.mode.upper()}] (Cooldown: {self.cooldown_seconds}s) para: {symbols}\n")

        async def on_price_update(data):
            if data.get("source") == "binance":
                symbol_raw = data["symbol"].replace("USDT", "")
                price = data["price"]
                now = time.time()

                # Control de Cooldown: ignorar ticks muy seguidos para el mismo simbolo
                last_time = self.last_order_time.get(symbol_raw, 0)
                if now - last_time < self.cooldown_seconds:
                    return

                self.last_order_time[symbol_raw] = now

                signal = {
                    "symbol": symbol_raw,
                    "question": symbol_raw,
                    "outcome": "YES",
                    "price": 0.45,
                    "size": 5.0
                }
                res = self.process_signal(signal)
                sys.stderr.write(f"[{self.mode.upper()} TICK] {symbol_raw} Spot: ${price:.2f} | Status: {res['status']} ({res['details']})\n")

        ws_feed = PriceFeedWebSocket(symbols=symbols)
        await ws_feed.start(callback=on_price_update)


def main():
    mode = "real" if "--real" in sys.argv else "paper"
    executor = DirectionalLimitHunterExecutor(mode=mode, cooldown_seconds=10.0)

    if "--live" in sys.argv:
        try:
            asyncio.run(executor.run_live_stream())
        except KeyboardInterrupt:
            print("\n[EXECUTOR] Feed en vivo detenido.")
    else:
        try:
            input_data = sys.stdin.read().strip()
            if not input_data:
                print("Uso: pasa un JSON por stdin. Flags opcionales: --live, --real")
                return

            signals = json.loads(input_data)
            if isinstance(signals, dict):
                signals = [signals]

            results = [executor.process_signal(sig) for sig in signals]
            executor.render_table(results)
        except Exception as e:
            sys.stderr.write(f"Error procesando entrada: {e}\n")


if __name__ == "__main__":
    main()
