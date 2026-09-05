import os
from tools.generate_pnl_report import parse_symbol_from_key, generate_report
from core.logger import PnLLogger

def test_parse_symbol_from_key():
    assert parse_symbol_from_key('0x123_BTC_YES_17000000', '0x123') == 'BTC'
    assert parse_symbol_from_key('0x456_ETH_NO_17000000', '0x456') == 'ETH'
    assert parse_symbol_from_key('0x789_UNKNOWN_17000000', '0x789') == 'OTROS'

def test_generate_report_flow(tmp_path, capsys):
    test_dir = str(tmp_path / 'data')
    csv_file = os.path.join(test_dir, 'test_trades.csv')
    logger = PnLLogger(output_dir=test_dir, filename='test_trades.csv')

    trade_btc = {
        'match_key': 'BTCUSDT_YES_1700000000',
        'condition_id': '0x123',
        'entry_price': 0.50,
        'close_price': 0.52,
        'pnl_pct': 0.04,
        'opened_at': 1000,
        'closed_at': 1300
    }
    logger.log_trade(trade_btc, trade_size_usd=100.0)

    generate_report(csv_file)
    captured = capsys.readouterr()
    assert 'REPORTE DE RENDIMIENTO DIRECTIONAL v1.5' in captured.out
    assert 'BTC' in captured.out
