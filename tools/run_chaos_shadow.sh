#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

INTERVAL="${INTERVAL:-60}"

echo "=============================================="
echo "CHAOS SHADOW - metralleta paper agresiva"
date
echo "Intervalo: ${INTERVAL}s"
echo "Trades file: data/chaos_shadow_trades.csv"
echo "=============================================="

while true; do
  echo
  echo "=== CHAOS CYCLE ==="
  date

  echo
  echo "Actualizando snapshot fresco..."
  python main.py crypto-snapshot \
    --gamma-source search \
    --search-query "bitcoin above" \
    --search-query "ethereum above" \
    --search-query "solana above" \
    --search-query "xrp above" \
    --event-limit 1000 \
    --market-limit 100 \
    --request-delay 0.2 \
    --market-profile crypto-price \
    --include-keyword above \
    --exclude-keyword "in July" \
    --exclude-keyword reach \
    --exclude-keyword dip \
    --exclude-keyword hit \
    --exclude-keyword GTA \
    --exclude-keyword tax \
    --exclude-keyword hack \
    --exclude-keyword liquidation \
    --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT \
    --interval 1m \
    --kline-limit 60 \
    --output-path data/crypto_signal_snapshot_fair_value.csv

  echo
  echo "Ejecutando chaos shadow..."
  PAPER_MAX_NEW_TRADES_PER_CYCLE=0 \
  RESEARCH_PAPER_ENABLED=0 \
  MICRO_TPSL_ENABLED=1 \
  MICRO_TPSL_TRADES_PATH=data/chaos_shadow_trades.csv \
  MICRO_TPSL_TRADE_USD=0.25 \
  MICRO_TPSL_MAX_OPEN=10 \
  MICRO_TPSL_MAX_NEW_TRADES_PER_CYCLE=5 \
  MICRO_TPSL_ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT \
  MICRO_TPSL_ALLOWED_OUTCOMES=Yes,No \
  MICRO_TPSL_ALLOWED_DECISIONS=CRYPTO_BUY_FAIR_EDGE,CRYPTO_WATCH_FAIR_EDGE,CRYPTO_WAIT_BINANCE_NOT_ALIGNED,CRYPTO_WAIT_LOW_ORDERBOOK_SCORE,CRYPTO_WAIT_SPREAD_TOO_WIDE \
  MICRO_TPSL_ALLOWED_ALIGNMENT=ALIGNED,NEUTRAL \
  MICRO_TPSL_ALLOWED_FLOW=BULLISH,BEARISH,NEUTRAL \
  MICRO_TPSL_MIN_EDGE=0.05 \
  MICRO_TPSL_MIN_SCORE=50 \
  MICRO_TPSL_MAX_SPREAD=0.05 \
  MICRO_TPSL_MIN_ASK=0.20 \
  MICRO_TPSL_MAX_ASK=0.80 \
  MICRO_TPSL_MIN_CONFIRMATIONS=1 \
  MICRO_TPSL_TAKE_PROFIT_PCT=3 \
  MICRO_TPSL_STOP_LOSS_PCT=6 \
  MICRO_TPSL_MAX_HOLD_MINUTES=60 \
  MICRO_TPSL_ENTRY_COOLDOWN_MINUTES=5 \
  python tools/micro_tpsl_paper_executor.py

  echo
  echo "Siguiente ciclo chaos en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
