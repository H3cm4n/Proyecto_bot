#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

INTERVAL="${INTERVAL:-300}"
ONCE="${ONCE:-0}"

mkdir -p data/universe_discovery

echo "=============================================="
echo "DIRECTIONAL LIMIT HUNTER SHADOW"
date
echo "Intervalo: ${INTERVAL}s"
echo "Orders file: data/directional_limit_hunter_orders.csv"
echo "Trades file: data/directional_limit_hunter_trades.csv"
echo "Filtered snapshot: data/directional_limit_hunter_snapshot.csv"
echo "Discovery source: data/universe_discovery/latest_combined.csv"
echo "=============================================="

while true; do
  echo
  echo "=== DIRECTIONAL LIMIT HUNTER CYCLE ==="
  date

  echo
  echo "Actualizando universo crypto above..."
  python tools/crypto_universe_discovery.py \
    --mode above \
    --event-limit 1000 \
    --market-limit 100 \
    --request-delay 0.25

  echo
  echo "Filtrando limit hunter..."
  LIMIT_HUNTER_SOURCE_SNAPSHOT=data/universe_discovery/latest_combined.csv \
  LIMIT_HUNTER_FILTERED_SNAPSHOT=data/directional_limit_hunter_snapshot.csv \
  LIMIT_HUNTER_SYMBOLS=BTCUSDT,ETHUSDT \
  LIMIT_HUNTER_ALLOWED_DECISIONS=CRYPTO_BUY_FAIR_EDGE,CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH \
  LIMIT_HUNTER_MIN_EDGE=0.20 \
  LIMIT_HUNTER_MIN_SCORE=65 \
  LIMIT_HUNTER_MAX_SPREAD=0.05 \
  LIMIT_HUNTER_MIN_ASK=0.50 \
  LIMIT_HUNTER_MAX_ASK=0.80 \
  LIMIT_HUNTER_LIMIT_OFFSET=0.03 \
  python tools/filter_directional_limit_hunter_snapshot.py

  echo
  echo "Ejecutando limit hunter paper..."
  LIMIT_HUNTER_SNAPSHOT_PATH=data/directional_limit_hunter_snapshot.csv \
  LIMIT_HUNTER_MARK_SNAPSHOT_PATH=data/universe_discovery/latest_combined.csv \
  LIMIT_HUNTER_ORDERS_PATH=data/directional_limit_hunter_orders.csv \
  LIMIT_HUNTER_TRADES_PATH=data/directional_limit_hunter_trades.csv \
  LIMIT_HUNTER_TRADE_USD=0.25 \
  LIMIT_HUNTER_MAX_OPEN=1 \
  LIMIT_HUNTER_MAX_PENDING=1 \
  LIMIT_HUNTER_MAX_NEW_ORDERS_PER_CYCLE=1 \
  LIMIT_HUNTER_TAKE_PROFIT_PCT=4 \
  LIMIT_HUNTER_STOP_LOSS_PCT=8 \
  LIMIT_HUNTER_MAX_HOLD_MINUTES=180 \
  LIMIT_HUNTER_PENDING_TTL_MINUTES=90 \
  LIMIT_HUNTER_ENTRY_COOLDOWN_MINUTES=60 \
  LIMIT_HUNTER_CANCEL_WHEN_SIGNAL_GONE=1 \
  LIMIT_HUNTER_SIGNAL_GONE_GRACE_CYCLES=3 \
  python tools/directional_limit_hunter_executor.py

  if [[ "$ONCE" == "1" ]]; then
    echo
    echo "ONCE=1 activo; terminando después de un ciclo."
    break
  fi

  echo
  echo "Siguiente ciclo Directional Limit Hunter en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
