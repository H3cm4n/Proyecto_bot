#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

INTERVAL="${INTERVAL:-300}"
ONCE="${ONCE:-0}"

mkdir -p data/universe_discovery

echo "=============================================="
echo "DIRECTIONAL UNIVERSE SHADOW - bullish YES / bearish NO"
date
echo "Intervalo: ${INTERVAL}s"
echo "Trades file: data/directional_universe_shadow_trades.csv"
echo "Filtered snapshot: data/directional_universe_shadow_snapshot.csv"
echo "Discovery source: data/universe_discovery/latest_combined.csv"
echo "=============================================="

while true; do
  echo
  echo "=== DIRECTIONAL UNIVERSE CYCLE ==="
  date

  echo
  echo "Actualizando universo crypto above..."
  python tools/crypto_universe_discovery.py \
    --mode above \
    --event-limit 1000 \
    --market-limit 100 \
    --request-delay 0.25

  echo
  echo "Filtrando Directional Universe..."
  DIRECTIONAL_SOURCE_SNAPSHOT=data/universe_discovery/latest_combined.csv \
  DIRECTIONAL_FILTERED_SNAPSHOT=data/directional_universe_shadow_snapshot.csv \
  DIRECTIONAL_SYMBOLS=BTCUSDT,ETHUSDT \
  DIRECTIONAL_MIN_EDGE=0.15 \
  DIRECTIONAL_MIN_SCORE=80 \
  DIRECTIONAL_MAX_SPREAD=0.01 \
  DIRECTIONAL_MIN_ASK=0.45 \
  DIRECTIONAL_MAX_ASK=0.65 \
  DIRECTIONAL_ALLOW_WAIT_ENTRY_HIGH=0 \
  python tools/filter_directional_universe_snapshot.py

  echo
  echo "Ejecutando Directional Universe paper..."
  TOPN_SNAPSHOT_PATH=data/directional_universe_shadow_snapshot.csv \
  TOPN_MARK_SNAPSHOT_PATH=data/universe_discovery/latest_combined.csv \
  TOPN_TRADES_PATH=data/directional_universe_shadow_trades.csv \
  TOPN_TRADE_USD=0.25 \
  TOPN_MAX_OPEN=2 \
  TOPN_MAX_NEW_PER_CYCLE=1 \
  TOPN_ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT \
  TOPN_ALLOWED_OUTCOMES=Yes,No \
  TOPN_MIN_EDGE=0.15 \
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
  echo "Siguiente ciclo Directional Universe en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
