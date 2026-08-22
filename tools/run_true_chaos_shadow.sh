#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

INTERVAL="${INTERVAL:-60}"

echo "=============================================="
echo "TRUE CHAOS SHADOW - paper hiper agresivo"
date
echo "Intervalo: ${INTERVAL}s"
echo "Trades file: data/true_chaos_shadow_trades.csv"
echo "=============================================="

while true; do
  echo
  echo "=== TRUE CHAOS CYCLE ==="
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
  echo "Ejecutando true chaos shadow..."
  PAPER_MAX_NEW_TRADES_PER_CYCLE=0 \
  RESEARCH_PAPER_ENABLED=0 \
  MICRO_TPSL_ENABLED=1 \
  MICRO_TPSL_TRADES_PATH=data/true_chaos_shadow_trades.csv \
  MICRO_TPSL_TRADE_USD=0.10 \
  MICRO_TPSL_MAX_OPEN=20 \
  MICRO_TPSL_MAX_NEW_TRADES_PER_CYCLE=10 \
  MICRO_TPSL_ALLOWED_SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT \
  MICRO_TPSL_ALLOWED_OUTCOMES=Yes,No \
  MICRO_TPSL_ALLOWED_DECISIONS=CRYPTO_BUY_FAIR_EDGE,CRYPTO_WATCH_FAIR_EDGE,CRYPTO_WAIT_BINANCE_NOT_ALIGNED,CRYPTO_WAIT_LOW_ORDERBOOK_SCORE,CRYPTO_WAIT_SPREAD_TOO_WIDE,CRYPTO_WAIT_ENTRY_ASK_TOO_HIGH,CRYPTO_WAIT_NO_FAIR_EDGE,CRYPTO_AVOID_BINANCE_CONFLICT,CRYPTO_AVOID_NEGATIVE_FAIR_EDGE,CRYPTO_AVOID_ASK_TOO_HIGH,CRYPTO_IGNORE_THRESHOLD_TOO_FAR \
  MICRO_TPSL_ALLOWED_ALIGNMENT=ALIGNED,NEUTRAL,CONFLICT \
  MICRO_TPSL_ALLOWED_FLOW=BULLISH,BEARISH,NEUTRAL \
  MICRO_TPSL_MIN_EDGE=-0.20 \
  MICRO_TPSL_MIN_SCORE=20 \
  MICRO_TPSL_MAX_SPREAD=0.15 \
  MICRO_TPSL_MIN_ASK=0.05 \
  MICRO_TPSL_MAX_ASK=0.95 \
  MICRO_TPSL_MIN_CONFIRMATIONS=1 \
  MICRO_TPSL_TAKE_PROFIT_PCT=2 \
  MICRO_TPSL_STOP_LOSS_PCT=4 \
  MICRO_TPSL_MAX_HOLD_MINUTES=30 \
  MICRO_TPSL_ENTRY_COOLDOWN_MINUTES=1 \
  python tools/micro_tpsl_paper_executor.py

  echo
  echo "Siguiente ciclo true chaos en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
