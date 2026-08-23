#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

INTERVAL="${INTERVAL:-300}"
ONCE="${ONCE:-0}"

mkdir -p data/universe_discovery

echo "=============================================="
echo "BEAR NO UNIVERSE SHADOW - discovery + bearish NO"
date
echo "Intervalo: ${INTERVAL}s"
echo "Trades file: data/bear_no_universe_shadow_trades.csv"
echo "Filtered snapshot: data/bear_no_universe_shadow_snapshot.csv"
echo "Discovery source: data/universe_discovery/latest_combined.csv"
echo "=============================================="

while true; do
  echo
  echo "=== BEAR NO UNIVERSE CYCLE ==="
  date

  echo
  echo "Actualizando universo crypto above..."
  python tools/crypto_universe_discovery.py \
    --mode above \
    --event-limit 1000 \
    --market-limit 100 \
    --request-delay 0.25

  echo
  echo "Filtrando Bear No desde universe discovery..."
  BEAR_NO_SOURCE_SNAPSHOT=data/universe_discovery/latest_combined.csv \
  BEAR_NO_FILTERED_SNAPSHOT=data/bear_no_universe_shadow_snapshot.csv \
  BEAR_NO_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT \
  BEAR_NO_MIN_EDGE=0.20 \
  BEAR_NO_MIN_SCORE=80 \
  BEAR_NO_MAX_SPREAD=0.01 \
  BEAR_NO_MIN_ASK=0.45 \
  BEAR_NO_MAX_ASK=0.65 \
  python tools/filter_bear_no_shadow_snapshot.py

  echo
  echo "Ejecutando Bear No Universe paper..."
  TOPN_SNAPSHOT_PATH=data/bear_no_universe_shadow_snapshot.csv \
  TOPN_MARK_SNAPSHOT_PATH=data/universe_discovery/latest_combined.csv \
  TOPN_TRADES_PATH=data/bear_no_universe_shadow_trades.csv \
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
  echo "Siguiente ciclo Bear No Universe en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
