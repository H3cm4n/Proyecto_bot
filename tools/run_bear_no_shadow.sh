#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

INTERVAL="${INTERVAL:-60}"
ONCE="${ONCE:-0}"

echo "=============================================="
echo "BEAR NO SHADOW - crypto bearish aligned NO"
date
echo "Intervalo: ${INTERVAL}s"
echo "Trades file: data/bear_no_shadow_trades.csv"
echo "Filtered snapshot: data/bear_no_shadow_snapshot.csv"
echo "=============================================="

while true; do
  echo
  echo "=== BEAR NO CYCLE ==="
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
  echo "Filtrando Bear No..."
  BEAR_NO_SOURCE_SNAPSHOT=data/crypto_signal_snapshot_fair_value.csv \
  BEAR_NO_FILTERED_SNAPSHOT=data/bear_no_shadow_snapshot.csv \
  BEAR_NO_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT \
  BEAR_NO_MIN_EDGE=0.20 \
  BEAR_NO_MIN_SCORE=80 \
  BEAR_NO_MAX_SPREAD=0.01 \
  BEAR_NO_MIN_ASK=0.45 \
  BEAR_NO_MAX_ASK=0.65 \
  python tools/filter_bear_no_shadow_snapshot.py

  echo
  echo "Ejecutando Bear No paper..."
  TOPN_SNAPSHOT_PATH=data/bear_no_shadow_snapshot.csv \
  TOPN_MARK_SNAPSHOT_PATH=data/crypto_signal_snapshot_fair_value.csv \
  TOPN_TRADES_PATH=data/bear_no_shadow_trades.csv \
  TOPN_TRADE_USD=0.25 \
  TOPN_MAX_OPEN=2 \
  TOPN_MAX_NEW_PER_CYCLE=1 \
  TOPN_ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT \
  TOPN_ALLOWED_OUTCOMES=No \
  TOPN_MIN_EDGE=0.20 \
  TOPN_MIN_SCORE=80 \
  TOPN_MAX_SPREAD=0.01 \
  TOPN_MIN_ASK=0.45 \
  TOPN_MAX_ASK=0.65 \
  TOPN_TAKE_PROFIT_PCT=4 \
  TOPN_STOP_LOSS_PCT=8 \
  TOPN_MAX_HOLD_MINUTES=180 \
  TOPN_ENTRY_COOLDOWN_MINUTES=60 \
  python tools/topn_shadow_executor.py

  if [[ "$ONCE" == "1" ]]; then
    echo
    echo "ONCE=1 activo; terminando después de un ciclo."
    break
  fi

  echo
  echo "Siguiente ciclo Bear No en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
