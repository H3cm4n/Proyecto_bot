#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

INTERVAL="${INTERVAL:-60}"

echo "=============================================="
echo "RAPID SHADOW - metralleta con cerebro"
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
  python - << 'PY'
import pandas as pd
from pathlib import Path

src = Path("data/crypto_signal_snapshot_fair_value.csv")
dst = Path("data/rapid_shadow_snapshot.csv")

df = pd.read_csv(src)

for col in ["best_bid", "best_ask", "spread", "score", "fair_edge_to_ask"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

mask = (
    df["crypto_symbol"].astype(str).str.upper().isin(["BTCUSDT", "ETHUSDT"])
    & (df["outcome"].astype(str).str.lower() == "yes")
    & (df["crypto_decision"].astype(str) == "CRYPTO_BUY_FAIR_EDGE")
    & (df["crypto_alignment"].astype(str) == "ALIGNED")
    & (df["flow_bias"].astype(str) == "BULLISH")
    & df["best_bid"].notna()
    & df["best_ask"].notna()
    & df["best_ask"].between(0.45, 0.70, inclusive="both")
    & (df["spread"].fillna(999) <= 0.02)
    & (df["score"].fillna(0) >= 70)
    & (df["fair_edge_to_ask"].fillna(-999) >= 0.15)
)

out = df[mask].copy()

if not out.empty:
    out = out.sort_values(
        ["fair_edge_to_ask", "score"],
        ascending=[False, False],
        na_position="last",
    )

out.to_csv(dst, index=False)

print("Rapid candidates:", len(out))
if not out.empty:
    cols = [
        "question",
        "outcome",
        "crypto_symbol",
        "best_bid",
        "best_ask",
        "spread",
        "score",
        "fair_edge_to_ask",
        "crypto_decision",
        "crypto_alignment",
        "flow_bias",
    ]
    cols = [c for c in cols if c in out.columns]
    print(out[cols].head(20).to_string(index=False))
PY

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

  echo
  echo "Siguiente ciclo rapid en ${INTERVAL}s..."
  sleep "$INTERVAL"
done
