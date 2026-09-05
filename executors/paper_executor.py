"""
executors/paper_executor.py
Motor de Paper Trading con gestión conservadora de PnL y manejo de órdenes stale.
"""

import time

class PaperExecutor:
    def __init__(self, max_open_trades=1, max_pending_orders=1, grace_cycles=3):
        self.max_open_trades = max_open_trades
        self.max_pending_orders = max_pending_orders
        self.grace_cycles = grace_cycles
        self.pending_orders = {}
        self.open_trades = {}
        self.trade_history = []

    def generate_match_key(self, condition_id: str, outcome: str) -> str:
        timestamp = int(time.time())
        return f"{condition_id}_{outcome}_{timestamp}"

    def process_signal(self, candidate: dict):
        if len(self.open_trades) >= self.max_open_trades:
            return {"status": "REJECTED", "reason": "MAX_OPEN_TRADES_REACHED"}

        if len(self.pending_orders) >= self.max_pending_orders:
            return {"status": "REJECTED", "reason": "MAX_PENDING_ORDERS_REACHED"}

        match_key = self.generate_match_key(candidate["condition_id"], candidate["outcome"])
        
        self.pending_orders[match_key] = {
            "match_key": match_key,
            "condition_id": candidate["condition_id"],
            "outcome": candidate["outcome"],
            "limit_price": candidate["limit_price"],
            "stale_counter": 0,
            "created_at": time.time()
        }
        return {"status": "PENDING_CREATED", "match_key": match_key}

    def update_orders_and_trades(self, market_snapshot: dict):
        for key, order in list(self.pending_orders.items()):
            cond_id = order["condition_id"]
            if cond_id not in market_snapshot:
                continue

            market = market_snapshot[cond_id]
            best_ask = market.get("best_ask", 1.0)
            binance_signal = market.get("binance_signal", "NEUTRAL")

            if binance_signal == "CONFLICT":
                del self.pending_orders[key]
                continue

            if best_ask <= order["limit_price"]:
                fill_price = min(order["limit_price"], best_ask)
                self.open_trades[key] = {
                    "match_key": key,
                    "condition_id": cond_id,
                    "entry_price": fill_price,
                    "target_tp": round(fill_price * 1.04, 4),
                    "target_sl": round(fill_price * 0.92, 4),
                    "opened_at": time.time()
                }
                del self.pending_orders[key]
            else:
                order["stale_counter"] += 1
                if order["stale_counter"] >= self.grace_cycles:
                    del self.pending_orders[key]

        for key, trade in list(self.open_trades.items()):
            cond_id = trade["condition_id"]
            if cond_id not in market_snapshot:
                continue

            market = market_snapshot[cond_id]
            best_bid = market.get("best_bid", 0.0)

            if best_bid >= trade["target_tp"] or best_bid <= trade["target_sl"]:
                pnl = round((best_bid - trade["entry_price"]) / trade["entry_price"], 4)
                trade["close_price"] = best_bid
                trade["pnl_pct"] = pnl
                trade["closed_at"] = time.time()
                
                self.trade_history.append(trade)
                del self.open_trades[key]
