import os
from core.logger import PnLLogger

def test_pnl_logger_flow(tmp_path):
    test_dir = str(tmp_path / "data")
    logger = PnLLogger(output_dir=test_dir, filename="test_trades.csv")

    trade_sample = {
        "match_key": "0x123_YES_1700000000",
        "condition_id": "0x123",
        "entry_price": 0.50,
        "close_price": 0.52,
        "pnl_pct": 0.04,
        "opened_at": 1000,
        "closed_at": 1050
    }

    logger.log_trade(trade_sample, trade_size_usd=100.0)

    assert os.path.exists(logger.filepath)

    stats = logger.calculate_stats()
    assert stats["total_trades"] == 1
    assert stats["win_rate"] == 1.0
    assert stats["total_pnl_usd"] == 4.0
