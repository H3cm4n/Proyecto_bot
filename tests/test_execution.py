import pytest
from core.orderbook import calculate_relative_spread, simulate_limit_fill
from executors.paper_executor import PaperExecutor

def test_relative_spread():
    assert calculate_relative_spread(0.45, 0.50) == pytest.approx(0.10)

def test_simulate_fill():
    result = simulate_limit_fill(limit_price=0.60, best_ask=0.58, ask_depth=100.0)
    assert result["filled"] is True
    assert result["fill_price"] == 0.58

def test_executor_conflict_cancellation():
    executor = PaperExecutor(grace_cycles=3)
    candidate = {"condition_id": "0x123", "outcome": "YES", "limit_price": 0.60}
    
    res = executor.process_signal(candidate)
    key = res["match_key"]
    
    snapshot = {"0x123": {"best_ask": 0.65, "best_bid": 0.60, "binance_signal": "CONFLICT"}}
    executor.update_orders_and_trades(snapshot)
    
    assert key not in executor.pending_orders
