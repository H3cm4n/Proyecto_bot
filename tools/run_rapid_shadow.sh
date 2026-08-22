#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

INTERVAL="${INTERVAL:-60}"
ONCE="${ONCE:-0}"

echo "=============================================="
echo "RAPID SHADOW - metralleta con cerebro v2"
date
echo "Intervalo: ${INTERVAL}s"
echo "Trades file: data/rapid_shadow_trades.csv"
echo "Filtered snapshot: data/rapid_shadow_snapshot.csv"
echo "=============================================="

while true; do
  echo
  echo "=== RAPID CYCLE ==="
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
  echo "Filtrando snapshot para rapid shadow..."
  RAPID_SOURCE_SNAPSHOT=data/crypto_signal_snapshot_fair_value.csv \
  RAPID_FILTERED_SNAPSHOT=data/rapid_shadow_snapshot.csv \
  RAPID_SYMBOLS=BTCUSDT,ETHUSDT \
  RAPID_MIN_EDGE=0.15 \
  RAPID_MIN_SCORE=70 \
  RAPID_MAX_SPREAD=0.02 \
  RAPID_MIN_ASK=0.45 \
  RAPID_MAX_ASK=0.70 \
  RAPID_REQUIRE_FLOW=0 \
  python tools/filter_rapid_shadow_snapshot.py

  echo
  echo "Ejecutando rapid shadow..."
  TOPN_SNAPSHOT_PATH=data/rapid_shadow_snapshot.csv \
  TOPN_TRADES_PATH=data/rapid_shadow_trades.csv \
  TOPN_TRADE_USD=0.25 \
  TOPN_MAX_OPEN=5 \
  TOPN_MAX_NEW_PER_CYCLE=3 \
  TOPN_ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT \
  TOPN_ALLOWED_OUTCOMES=Yes \
  TOPN_MIN_EDGE=0.15 \
  TOPN_MIN_SCORE=70 \
  TOPN_MAX_SPREAD=0.02 \
  TOPN_MIN_ASK=0.45 \
  TOPN_MAX_ASK=0.70 \
  TOPN_TAKE_PROFIT_PCT=3 \
  TOPN_STOP_LOSS_PCT=5 \
  TOPN_MAX_HOLD_MINUTES=90 \
  TOPN_ENTRY_COOLDOWN_MINUTES=15 \
  python tools/topn_shadow_executor.py

  if [[ "$ONCE" == "1" ]]; then
    echo
    echo "ONCE=1 activo; terminando después de un ciclo."
    break
  fi

  echo
  echo "Siguiente ciclo rapid en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
