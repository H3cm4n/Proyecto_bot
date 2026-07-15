#!/usr/bin/env bash
set -u

INTERVAL="${INTERVAL:-60}"
OUT="data/crypto_signal_snapshot_fair_value.csv"
LOG="data/crypto_live_last.log"
UPDOWN_PROBE_LOG="data/updown_clob_probe_last.log"
UPDOWN_PROBE_ENABLED="${UPDOWN_PROBE_ENABLED:-1}"
UPDOWN_PROBE_EVERY_CYCLES="${UPDOWN_PROBE_EVERY_CYCLES:-5}"
CYCLE=0

mkdir -p data

while true; do
  CYCLE=$((CYCLE + 1))
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

  python tools/binance_flow_report.py
  python tools/candidate_journal.py "$OUT"
  python tools/research_lane_report.py "$OUT"
  python tools/research_paper_executor.py "$OUT"

  echo
  echo "=== UP/DOWN CLOB PROBE ==="
  if [ "$UPDOWN_PROBE_ENABLED" = "1" ] && [ $((CYCLE % UPDOWN_PROBE_EVERY_CYCLES)) -eq 0 ]; then
    echo "Ejecutando probe Up/Down CLOB ciclo $CYCLE..."
    python tools/probe_updown_clob.py > "$UPDOWN_PROBE_LOG" 2>&1
    tail -n 25 "$UPDOWN_PROBE_LOG"
  else
    echo "Saltando probe Up/Down CLOB en este ciclo."
    echo "Frecuencia: cada $UPDOWN_PROBE_EVERY_CYCLES ciclos."
    echo "Último log: $UPDOWN_PROBE_LOG"
  fi

  echo
  python tools/market_router.py

  MARKET_ROUTE="$(python - << 'PYROUTE'
import json
from pathlib import Path

path = Path("data/market_router_last.json")
if not path.exists():
    print("NONE")
    raise SystemExit(0)

try:
    data = json.loads(path.read_text())
except Exception:
    print("NONE")
    raise SystemExit(0)

print(data.get("route") or "NONE")
PYROUTE
)"

  echo
  echo "Market route para executor: $MARKET_ROUTE"
  python tools/market_router_journal.py

  if [ "$MARKET_ROUTE" = "ABOVE_DATE" ]; then
    python tools/check_buy_signal.py "$OUT"
    code="$?"

    python tools/paper_executor.py "$OUT"
  else
    echo "Router no eligió ABOVE_DATE; bloqueando nuevas entradas paper."
    echo "Las posiciones abiertas todavía se actualizan/cerrarían si existieran."

    code="0"
    PAPER_MAX_NEW_TRADES_PER_CYCLE=0 python tools/paper_executor.py "$OUT"
  fi
  python tools/signal_journal.py "$OUT"
  python tools/cycle_journal.py "$OUT"
  python tools/paper_report.py data/paper_trades.csv

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
