#!/usr/bin/env bash

# Configurar PYTHONPATH
export PYTHONPATH=.

# Crear directorio de datos si no existe
mkdir -p data/universe_discovery

# Usar el ejecutable de Python del entorno virtual
PYTHON_BIN=".venv/bin/python3"

# Si no existe el venv, intentar usar python3 del sistema
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

INTERVAL=${INTERVAL:-300}
RUN_ID=$(date -u +"%Y%m%dT%H%M%SZ")

echo "=============================================="
echo "DIRECTIONAL LIMIT HUNTER SHADOW v1.5"
echo "Run ID: ${RUN_ID}"
echo "Intervalo: ${INTERVAL}s"
echo "=============================================="

cleanup() {
    echo ""
    echo "[!] Cancelación recibida. Cerrando sesión..."
    exit 0
}

trap cleanup SIGINT SIGTERM

while true; do
    echo "=== CICLO DE EJECUCIÓN ($(date -u +"%Y%m%dT%H%M%SZ")) ==="
    
    # 1. Discovery
    echo "[1/3] Ejecutando Discovery..."
    $PYTHON_BIN main.py crypto-snapshot \
        --gamma-source search \
        --search-query "bitcoin price above" \
        --search-query "ethereum price above" \
        --search-query "solana price above" \
        --search-query "xrp price above" \
        --search-query "crypto above" \
        --event-limit 1000 \
        --market-limit 100 \
        --request-delay 0.25 \
        --market-profile crypto-price \
        --include-keyword above \
        --exclude-keyword GTA \
        --exclude-keyword tax \
        --exclude-keyword hack \
        --exclude-keyword liquidation \
        --symbols BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT \
        --interval 1m \
        --kline-limit 60 \
        --output-path data/universe_discovery/latest_snapshot.json || true

    # 2. Filter v1.5
    echo "[2/3] Filtrando candidatos v1.5..."
    if [ -f "data/universe_discovery/latest_snapshot.json" ]; then
        $PYTHON_BIN tools/filter_directional_limit_hunter_snapshot.py < data/universe_discovery/latest_snapshot.json > data/directional_limit_hunter_snapshot.json 2>/dev/null || true
    fi

    # 3. Executor v1.5
    echo "[3/3] Ejecutando órdenes v1.5..."
    if [ -f "data/directional_limit_hunter_snapshot.json" ]; then
        $PYTHON_BIN tools/directional_limit_hunter_executor.py < data/directional_limit_hunter_snapshot.json || true
    fi

    if [ "${ONCE}" = "1" ]; then
        echo "[i] Ejecución única (ONCE=1) finalizada."
        break
    fi

    echo "Esperando ${INTERVAL}s para el siguiente ciclo..."
    sleep "${INTERVAL}"
done
