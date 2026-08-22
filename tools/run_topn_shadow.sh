#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

INTERVAL="${INTERVAL:-60}"

echo "=============================================="
echo "TOPN SHADOW - casino lab"
date
echo "Intervalo: ${INTERVAL}s"
echo "Trades file: data/topn_shadow_trades.csv"
echo "=============================================="

while true; do
  echo
  echo "=== TOPN CYCLE ==="
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
  echo "Ejecutando TopN shadow..."
  TOPN_TRADES_PATH=data/topn_shadow_trades.csv \
  TOPN_TRADE_USD=0.10 \
  TOPN_MAX_OPEN=20 \
  TOPN_MAX_NEW_PER_CYCLE=10 \
  TOPN_ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT \
  TOPN_ALLOWED_OUTCOMES=Yes,No \
  TOPN_MIN_EDGE=-999 \
  TOPN_MIN_SCORE=0 \
  TOPN_MAX_SPREAD=0.25 \
  TOPN_MIN_ASK=0.02 \
  TOPN_MAX_ASK=0.98 \
  TOPN_TAKE_PROFIT_PCT=2 \
  TOPN_STOP_LOSS_PCT=4 \
  TOPN_MAX_HOLD_MINUTES=30 \
  TOPN_ENTRY_COOLDOWN_MINUTES=1 \
  python tools/topn_shadow_executor.py

  echo
  echo "Siguiente ciclo TopN en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
