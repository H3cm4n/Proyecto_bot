#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! grep -q "MICRO_TPSL_TRADES_PATH" tools/micro_tpsl_paper_executor.py; then
  echo "ERROR: micro_tpsl_paper_executor.py no parece soportar MICRO_TPSL_TRADES_PATH."
  echo "No ejecuto ETH shadow para no contaminar data/micro_tpsl_paper_trades.csv."
  exit 1
fi

INTERVAL="${INTERVAL:-60}"

echo "=============================================="
echo "ETH MICRO SHADOW - paper separado"
date
echo "Intervalo: ${INTERVAL}s"
echo "Trades file: data/eth_micro_tpsl_shadow_trades.csv"
echo "=============================================="

while true; do
  echo
  echo "=== ETH SHADOW CYCLE ==="
  date

  PAPER_MAX_NEW_TRADES_PER_CYCLE=0 \
  RESEARCH_PAPER_ENABLED=0 \
  MICRO_TPSL_ENABLED=1 \
  MICRO_TPSL_TRADES_PATH=data/eth_micro_tpsl_shadow_trades.csv \
  MICRO_TPSL_TRADE_USD=2 \
  MICRO_TPSL_MAX_OPEN=1 \
  MICRO_TPSL_MAX_NEW_TRADES_PER_CYCLE=1 \
  MICRO_TPSL_ALLOWED_SYMBOLS=ETHUSDT \
  MICRO_TPSL_ALLOWED_OUTCOMES=Yes \
  MICRO_TPSL_ALLOWED_DECISIONS=CRYPTO_BUY_FAIR_EDGE \
  MICRO_TPSL_ALLOWED_ALIGNMENT=ALIGNED \
  MICRO_TPSL_ALLOWED_FLOW=BULLISH \
  MICRO_TPSL_MIN_EDGE=0.20 \
  MICRO_TPSL_MIN_SCORE=80 \
  MICRO_TPSL_MAX_SPREAD=0.01 \
  MICRO_TPSL_MIN_ASK=0.50 \
  MICRO_TPSL_MAX_ASK=0.60 \
  MICRO_TPSL_MIN_CONFIRMATIONS=1 \
  MICRO_TPSL_TAKE_PROFIT_PCT=4 \
  MICRO_TPSL_STOP_LOSS_PCT=8 \
  MICRO_TPSL_MAX_HOLD_MINUTES=180 \
  MICRO_TPSL_ENTRY_COOLDOWN_MINUTES=90 \
  python tools/micro_tpsl_paper_executor.py

  echo
  echo "Siguiente lectura ETH shadow en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
