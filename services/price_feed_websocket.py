"""
services/price_feed_websocket.py
Servicio de feeds en tiempo real vía WebSockets para Binance y Polymarket CLOB.
"""

import sys
import json
import asyncio
import websockets


class PriceFeedWebSocket:
    def __init__(self, symbols=None, token_ids=None):
        self.symbols = [s.lower() + "usdt" for s in (symbols or ["eth", "btc"])]
        self.token_ids = token_ids or []
        self.latest_prices = {}

    async def connect_binance(self, callback=None):
        """
        Se conecta al WebSocket Stream de Binance para tickers en tiempo real.
        """
        streams = "/".join([f"{s}@trade" for s in self.symbols])
        url = f"wss://stream.binance.com:9443/ws/{streams}"

        sys.stderr.write(f"[WS-BINANCE] Conectando a {url}...\n")
        try:
            async with websockets.connect(url) as ws:
                sys.stderr.write("[WS-BINANCE] Conexión establecida.\n")
                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    symbol = data.get("s")
                    price = float(data.get("p", 0.0))

                    self.latest_prices[symbol] = price
                    
                    if callback:
                        await callback({"source": "binance", "symbol": symbol, "price": price})
        except Exception as e:
            sys.stderr.write(f"[WS-BINANCE] Error de conexión: {e}\n")

    async def connect_polymarket(self, callback=None):
        """
        Se conecta al WebSocket del Orderbook de Polymarket CLOB.
        """
        url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
        sys.stderr.write(f"[WS-POLYMARKET] Conectando a {url}...\n")

        try:
            async with websockets.connect(url) as ws:
                sys.stderr.write("[WS-POLYMARKET] Conexión establecida.\n")
                
                # Suscribirse a los token_ids si existen
                if self.token_ids:
                    sub_msg = {
                        "assets_ids": self.token_ids,
                        "type": "market"
                    }
                    await ws.send(json.dumps(sub_msg))

                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    
                    if callback:
                        await callback({"source": "polymarket", "raw": data})
        except Exception as e:
            sys.stderr.write(f"[WS-POLYMARKET] Error de conexión: {e}\n")

    async def start(self, callback=None):
        """
        Ejecuta ambos feeds concurrentemente mediante asyncio.gather.
        """
        tasks = [self.connect_binance(callback)]
        if self.token_ids:
            tasks.append(self.connect_polymarket(callback))
            
        await asyncio.gather(*tasks)


# Script de prueba independiente
if __name__ == "__main__":
    async def print_price(data):
        if data["source"] == "binance":
            print(f"[PRICE STREAM] Binance {data['symbol']}: ${data['price']:.2f}")

    feed = PriceFeedWebSocket(symbols=["eth", "btc"])
    try:
        asyncio.run(feed.start(callback=print_price))
    except KeyboardInterrupt:
        print("\nFeed detenido por el usuario.")
