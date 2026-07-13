#!/usr/bin/env bash
set -u

INTERVAL="${INTERVAL:-60}"
OUT="data/crypto_signal_snapshot_fair_value.csv"
LOG="data/crypto_live_last.log"

mkdir -p data

while true; do
  clear
  echo "=============================================="
  echo "CRYPTO LIVE MONITOR - Binance-first"
  date
  echo "Intervalo: ${INTERVAL}s"
  echo "=============================================="

  echo
  echo "Actualizando snapshot..."
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
    --include-keyword "above" \
    --exclude-keyword "in July" \
    --exclude-keyword "reach" \
    --exclude-keyword "dip" \
    --exclude-keyword "hit" \
    --exclude-keyword "GTA" \
    --exclude-keyword "tax" \
    --exclude-keyword "hack" \
    --exclude-keyword "liquidation" \
    --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT \
    --interval 1m \
    --kline-limit 60 \
    --output-path "$OUT" > "$LOG" 2>&1

  code="$?"

  if [ "$code" != "0" ]; then
    echo "ERROR actualizando snapshot. Revisa: $LOG"
    tail -n 40 "$LOG"
    sleep "$INTERVAL"
    continue
  fi

  python tools/crypto_report.py "$OUT"

  python tools/check_buy_signal.py "$OUT"
  code="$?"

  python tools/paper_executor.py "$OUT"

  if [ "$code" = "2" ]; then
    echo
    echo "🚨 ALERTA BUY DETECTADA 🚨"
    printf '\a'
  fi

  echo
  echo "Log completo del snapshot: $LOG"
  echo "Siguiente lectura en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
