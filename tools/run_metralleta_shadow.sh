#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

INTERVAL="${INTERVAL:-60}"

echo "=============================================="
echo "METRALLETA SHADOW - simulación agresiva"
date
echo "Intervalo: ${INTERVAL}s"
echo "Trades file: data/metralleta_shadow_trades.csv"
echo "=============================================="

while true; do
  echo
  echo "=== METRALLETA CYCLE ==="
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
  echo "Ejecutando metralleta shadow..."
  PAPER_MAX_NEW_TRADES_PER_CYCLE=0 \
  RESEARCH_PAPER_ENABLED=0 \
  MICRO_TPSL_ENABLED=1 \
  MICRO_TPSL_TRADES_PATH=data/metralleta_shadow_trades.csv \
  MICRO_TPSL_TRADE_USD=1 \
  MICRO_TPSL_MAX_OPEN=3 \
  MICRO_TPSL_MAX_NEW_TRADES_PER_CYCLE=2 \
  MICRO_TPSL_ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT \
  MICRO_TPSL_ALLOWED_OUTCOMES=Yes \
  MICRO_TPSL_ALLOWED_DECISIONS=CRYPTO_BUY_FAIR_EDGE \
  MICRO_TPSL_ALLOWED_ALIGNMENT=ALIGNED \
  MICRO_TPSL_ALLOWED_FLOW=BULLISH \
  MICRO_TPSL_MIN_EDGE=0.15 \
  MICRO_TPSL_MIN_SCORE=70 \
  MICRO_TPSL_MAX_SPREAD=0.02 \
  MICRO_TPSL_MIN_ASK=0.45 \
  MICRO_TPSL_MAX_ASK=0.70 \
  MICRO_TPSL_MIN_CONFIRMATIONS=1 \
  MICRO_TPSL_TAKE_PROFIT_PCT=4 \
  MICRO_TPSL_STOP_LOSS_PCT=8 \
  MICRO_TPSL_MAX_HOLD_MINUTES=120 \
  MICRO_TPSL_ENTRY_COOLDOWN_MINUTES=30 \
  python tools/micro_tpsl_paper_executor.py

  echo
  echo "Siguiente ciclo metralleta en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
